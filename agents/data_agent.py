"""
Data Agent

Fetches data from the MediNote backend via tool calling.
Exposes two interfaces:
  - stream(question)  → generator yielding protocol events (for CLI display)
  - fetch(question)   → blocking, returns DataResult (for pipeline use)
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Iterator

import requests
from openai import OpenAI

import config
from core.backend_client import BackendClient
from core.entity_rag import EntityRAG
from core.rag import TableRAG
from core.tools import TOOLS, format_tool_result

MAX_TOOL_ROUNDS = 10

_LOCAL_PATTERNS = [
    (re.compile(r"how many (tables|table)", re.I),                         "count_tables"),
    (re.compile(r"how many (modules|module)", re.I),                        "count_modules"),
    (re.compile(r"(list|show|give|what).{0,20}(all )?(tables|table)", re.I),"list_tables"),
    (re.compile(r"(list|show|give|what).{0,20}(all )?(modules|module)", re.I),"list_modules"),
    (re.compile(r"(show|give|what is|print|display).{0,20}(schema|database)", re.I), "show_schema"),
]

# Key tables whose exact columns are injected into the system prompt at runtime
_KEY_TABLES = {
    # VENTES
    "ca_tot_vente":        "Daily sales transactions — general sales queries by date/delegate/zone",
    "ca_prd_day":          "Daily sales per product",
    "ca_prd_month":        "Monthly pre-aggregated sales per product",
    "ca_qte_prd_year_gro": "Yearly pre-aggregated quantities per product group",
    "ca_zone_year_fam":    "Yearly pre-aggregated CA per zone and family",
    "ca_zone_real_time":   "Real-time CA per zone",
    "ca_gamme_real_time":  "Real-time CA per product line",
    "cl_reliquat_dlg":     "Outstanding balances per delegate",
    # PRODUITS_STOCK
    "art_stock_day":       "Daily stock levels per article",
    "art_prod_day":        "Daily production per article",
    "art_entre_sortie":    "Stock entries and exits",
    "art_vente_fam":       "Sales by product family",
    # ANIMATION
    "annimation_fiches":         "Animation session records (field visits)",
    "annimation_fiches_produits":"Products presented per session",
    "annimation_ventes":         "Sales made during animations",
    # FINANCE
    "cl_reliquat":   "Client outstanding balances (ADMIN/STAFF only)",
    "cl_reglement":  "Client payments (ADMIN/STAFF only)",
    "bl_fact":       "Billing / invoices (ADMIN/STAFF only)",
    "budget_conso":  "Budget consumption (ADMIN/STAFF only)",
}


@dataclass
class DataResult:
    data: dict | None = None          # raw backend TableResponseDto
    error: str | None = None          # error message if fetch failed
    timing: list[tuple] = field(default_factory=list)  # [(kind, label, ms)]
    rag_tables: list[str] = field(default_factory=list)
    clarified_question: str = ""
    analysis_spec: str = ""           # passed through from Orchestrator → Analysis Agent
    analysis: str = ""                # explanation produced by Analysis Agent


class DataAgent:
    def __init__(
        self,
        client: BackendClient,
        rag: TableRAG | None = None,
        entity_rag: EntityRAG | None = None,
    ):
        self.backend = client
        self.rag = rag
        self.entity_rag = entity_rag
        self._llm = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
        self._schema: dict | None = None
        self._module_table_map: str = ""

    # ── Public interfaces ─────────────────────────────────────────────

    def load_schema(self) -> None:
        self._schema = self.backend.get_schema()
        self._module_table_map = self._build_compact_map(self._schema)

    def fetch(self, question: str) -> DataResult:
        """Blocking pipeline interface. Runs the full agent loop and returns a DataResult."""
        result = DataResult(clarified_question=question)
        answer_parts: list[str] = []
        llm_round = 0

        for chunk in self.stream(question):
            if chunk.startswith("__rag__:"):
                parts = chunk.split(":", 2)
                tables = parts[2].split(",") if len(parts) > 2 and parts[2] else []
                result.rag_tables = [t for t in tables if t]

            elif chunk.startswith("__timing__:llm:"):
                llm_round += 1
                ms = int(chunk.split(":")[2])
                result.timing.append(("llm", f"LLM round {llm_round}", ms))

            elif chunk.startswith("__timing__:tool:"):
                parts = chunk.split(":", 3)
                ms = int(parts[3])
                result.timing.append(("tool", parts[2], ms))

            elif chunk.startswith("__raw_result__:"):
                try:
                    result.data = json.loads(chunk[len("__raw_result__:"):])
                except Exception:
                    result.error = "Failed to parse backend response"

            elif not chunk.startswith("__"):
                answer_parts.append(chunk)

        if result.data is None and answer_parts:
            result.error = "".join(answer_parts).strip()

        return result

    def stream(self, question: str) -> Iterator[str]:
        """
        Generator for CLI streaming. Yields protocol events:
          __rag__:<count>:<tables>
          __timing__:llm:<ms>
          __timing__:tool:<name>:<ms>
          __tool_call__:<name>:<args_json>
          __raw_result__:<json>   — final verified data
          plain text              — error or explanation
        """
        if not self._schema:
            self.load_schema()

        local = self._try_local(question)
        if local is not None:
            yield "__timing__:local:0"
            yield local
            return

        rag_results, rag_context = self._rag_context(question)
        yield f"__rag__:{len(rag_results)}:{','.join(r['table'] for r in rag_results)}"

        entity_context = self._entity_context(question)

        messages: list[dict] = [
            {"role": "system", "content": self._system_prompt(rag_context, entity_context)},
            {"role": "user",   "content": question},
        ]

        _pending_result: dict | None = None  # last good data result awaiting VERIFIED

        for round_num in range(MAX_TOOL_ROUNDS):
            is_last = round_num == MAX_TOOL_ROUNDS - 1
            if is_last:
                messages.append({
                    "role": "user",
                    "content": "You must respond now. If you have data, say VERIFIED. Otherwise explain why you cannot answer.",
                })

            t0 = time.perf_counter()
            response = self._llm.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="none" if is_last else "auto",
            )
            yield f"__timing__:llm:{int((time.perf_counter() - t0) * 1000)}"

            msg = response.choices[0].message
            messages.append(msg.model_dump(exclude_unset=True))

            if not msg.tool_calls:
                # LLM produced text — either VERIFIED or an explanation
                content = (msg.content or "").strip()
                if content.upper().startswith("VERIFIED") and _pending_result is not None:
                    yield f"__raw_result__:{json.dumps(_pending_result, ensure_ascii=False, default=str)}"
                else:
                    yield content or "(no response)"
                return

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                yield f"__tool_call__:{name}:{json.dumps(args)}\n"

                t0 = time.perf_counter()
                result_data = self._dispatch(name, args)
                yield f"__timing__:tool:{name}:{int((time.perf_counter() - t0) * 1000)}"

                if name in ("query_table", "aggregate_table", "browse_table", "compare_periods"):
                    yield f"__query_detail__:{name}:{json.dumps(args, ensure_ascii=False)}"

                    total_rows = result_data.get("totalRows", -1) if isinstance(result_data, dict) else -1
                    has_error  = "error" in result_data if isinstance(result_data, dict) else False

                    # Store as candidate result for VERIFIED
                    if not has_error and total_rows != 0:
                        _pending_result = result_data

                    # Build feedback hint for LLM
                    if has_error:
                        hint = f"\n[ERROR from backend — fix the query and retry]"
                    elif total_rows == 0:
                        hint = f"\n[0 rows — wrong table or filters matched nothing, try a different approach]"
                    else:
                        hint = (
                            f"\n[{total_rows} rows returned — if this data answers the question, "
                            f"respond VERIFIED immediately. Do NOT fetch more data unless something is clearly missing.]"
                        )

                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "name":         name,
                        "content":      format_tool_result(result_data) + hint,
                    })
                else:
                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "name":         name,
                        "content":      format_tool_result(result_data),
                    })

        yield "Reached maximum tool-call rounds without a final answer."

    # ── Local handlers ────────────────────────────────────────────────

    def _try_local(self, question: str) -> str | None:
        for pattern, intent in _LOCAL_PATTERNS:
            if pattern.search(question):
                return getattr(self, f"_local_{intent}")()
        return None

    def _local_count_tables(self) -> str:
        n = sum(len(t) for t in self._schema.values())
        return f"There are **{n} tables** across {len(self._schema)} modules."

    def _local_count_modules(self) -> str:
        return f"There are **{len(self._schema)} modules**: {', '.join(self._schema.keys())}."

    def _local_list_tables(self) -> str:
        lines = []
        for module, tables in self._schema.items():
            lines.append(f"**{module}** ({len(tables)}): {', '.join(sorted(tables.keys()))}")
        return "\n".join(lines)

    def _local_list_modules(self) -> str:
        return "\n".join(f"**{m}** — {len(t)} tables" for m, t in self._schema.items())

    def _local_show_schema(self) -> str:
        lines = ["## Database Schema\n"]
        for module, tables in self._schema.items():
            lines.append(f"### {module}")
            for tbl, cols in tables.items():
                col_str = ", ".join(f"`{c['name']}`" for c in cols)
                lines.append(f"- **{tbl}**: {col_str}")
            lines.append("")
        return "\n".join(lines)

    # ── Tool dispatcher ───────────────────────────────────────────────

    def _dispatch(self, name: str, args: dict):
        b = self.backend
        try:
            if name == "search_schema":
                return self._search_schema(args.get("keyword", ""))

            elif name == "list_modules":
                return {m: list(t.keys()) for m, t in (self._schema or {}).items()}

            elif name == "list_tables":
                module = args.get("module")
                if module and self._schema and module in self._schema:
                    return list(self._schema[module].keys())
                return [t for tables in (self._schema or {}).values() for t in tables]

            elif name == "get_table_columns":
                table = args["table"]
                if self._schema:
                    for module_tables in self._schema.values():
                        if table in module_tables:
                            return module_tables[table]
                return b.get_columns(table)

            elif name == "query_table":
                body: dict = {}
                if args.get("filters"):
                    body["filters"] = args["filters"]
                if args.get("sort"):
                    body["sort"] = args["sort"]
                body["page"] = args.get("page", 0)
                body["size"] = args.get("size", 50)
                return b.query_table(args["table"], body)

            elif name == "aggregate_table":
                body: dict = {
                    "metrics": args["metrics"],
                    "page":    args.get("page", 0),
                    "size":    args.get("size", 50),
                }
                if args.get("groupBy"):
                    body["groupBy"] = args["groupBy"]
                if args.get("groupByExpressions"):
                    body["groupByExpressions"] = args["groupByExpressions"]
                if args.get("filters"):
                    body["filters"] = args["filters"]
                if args.get("having"):
                    body["having"] = args["having"]
                if args.get("sorts"):
                    body["sorts"] = args["sorts"]
                elif args.get("sort"):
                    body["sort"] = args["sort"]
                return b.aggregate_table(args["table"], body)

            elif name == "compare_periods":
                return self._compare_periods(args)

            elif name == "browse_table":
                return b.browse_table(
                    args["table"],
                    page=args.get("page", 0),
                    size=args.get("size", 20),
                )

            else:
                return {"error": f"Unknown tool: {name}"}

        except requests.HTTPError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Unexpected error in {name}: {e}"}

    def _compare_periods(self, args: dict) -> dict:
        """Execute two aggregate calls and merge them side-by-side with growth %."""
        table       = args["table"]
        date_col    = args["date_column"]
        period_a    = args["period_a"]
        period_b    = args["period_b"]
        group_cols  = args.get("groupBy", [])
        metrics     = args.get("metrics", [])
        extra       = args.get("extra_filters", [])
        sort_by     = args.get("sort_by")
        sort_dir    = args.get("sort_dir", "desc")
        size        = args.get("size", 50)

        if not group_cols:
            return {
                "error": (
                    "compare_periods requires at least one groupBy column. "
                    "For a grand-total comparison (no breakdown), use aggregate_table instead: "
                    "groupByExpressions=[YEAR(date) AS annee], "
                    "filters=[date between ['YYYY-01-01','YYYY-12-31']] covering both years. "
                    "That returns one row per year which directly answers the comparison."
                )
            }

        def _body(period: dict) -> dict:
            date_filters = [
                {"column": date_col, "operator": "gte", "value": period["date_start"]},
                {"column": date_col, "operator": "lte", "value": period["date_end"]},
            ]
            b: dict = {
                "groupBy": group_cols,
                "metrics": metrics,
                "filters": date_filters + extra,
                "page":    0,
                "size":    size,
            }
            if sort_by:
                b["sort"] = {"column": sort_by, "direction": sort_dir}
            return b

        res_a = self.backend.aggregate_table(table, _body(period_a))
        res_b = self.backend.aggregate_table(table, _body(period_b))

        if isinstance(res_a, dict) and "error" in res_a:
            return res_a
        if isinstance(res_b, dict) and "error" in res_b:
            return res_b

        la = period_a["label"]
        lb = period_b["label"]
        rows_a = {tuple(r.get(g) for g in group_cols): r for r in (res_a.get("rows") or [])}

        merged = []
        for rb in (res_b.get("rows") or []):
            key = tuple(rb.get(g) for g in group_cols)
            ra  = rows_a.get(key, {})
            row: dict = {g: rb.get(g) for g in group_cols}
            for m in metrics:
                alias = m["alias"]
                val_a = float(ra.get(alias) or 0)
                val_b = float(rb.get(alias) or 0)
                row[f"{alias}_{la}"] = val_a
                row[f"{alias}_{lb}"] = val_b
                row[f"{alias}_growth_pct"] = (
                    round((val_b - val_a) / abs(val_a) * 100, 2) if val_a else None
                )
            merged.append(row)

        if sort_by and merged:
            reverse = sort_dir == "desc"
            merged.sort(
                key=lambda r: (r.get(sort_by) is None, r.get(sort_by) or 0),
                reverse=reverse,
            )

        columns = list(group_cols)
        for m in metrics:
            columns += [f"{m['alias']}_{la}", f"{m['alias']}_{lb}", f"{m['alias']}_growth_pct"]

        return {
            "table":      table,
            "period_a":   la,
            "period_b":   lb,
            "totalRows":  len(merged),
            "totalPages": 1,
            "columns":    columns,
            "rows":       merged,
        }

    def _search_schema(self, keyword: str) -> list[dict]:
        if not self._schema or not keyword:
            return []
        kw = keyword.lower()
        results = []
        for module, tables in self._schema.items():
            for table, cols in tables.items():
                if kw in table.lower() or any(kw in c["name"].lower() for c in cols):
                    results.append({
                        "module": module,
                        "table":  table,
                        "columns": cols,
                    })
        return results

    # ── Entity RAG ────────────────────────────────────────────────────

    def _entity_context(self, question: str) -> str:
        if not self.entity_rag:
            return ""
        try:
            return self.entity_rag.search(question)
        except Exception:
            return ""

    # ── RAG ───────────────────────────────────────────────────────────

    def _rag_context(self, question: str) -> tuple[list[dict], str]:
        if not self.rag:
            return [], ""
        try:
            results = self.rag.search(question, top_k=5)
        except Exception:
            return [], ""
        if not results:
            return [], ""

        lines = ["## RELEVANT TABLES FROM DOCUMENTATION (ranked by relevance)\n"]
        for r in results:
            lines.append(f"### {r['table']}  (module: {r['module']})")
            lines.append(r["text"])
            lines.append("")
        return results, "\n".join(lines)

    # ── Prompts ───────────────────────────────────────────────────────

    def _build_key_table_columns(self) -> str:
        """Inject exact column names for key tables so the model never guesses."""
        if not self._schema:
            return ""
        lines = ["## KEY TABLE COLUMNS (exact names — use these directly, do not guess)\n"]
        for module_tables in self._schema.values():
            for table, cols in module_tables.items():
                if table not in _KEY_TABLES:
                    continue
                col_parts = []
                for c in cols:
                    base_type = c["type"].split("(")[0]
                    col_parts.append(f"{c['name']}:{base_type}")
                lines.append(
                    f"  {table} — {_KEY_TABLES[table]}\n"
                    f"    columns: {', '.join(col_parts)}"
                )
        return "\n".join(lines)

    def _system_prompt(self, rag_context: str = "", entity_context: str = "") -> str:
        table_context = rag_context if rag_context else (
            "## ALL MODULES AND TABLES\n" + self._module_table_map
        )
        key_columns = self._build_key_table_columns()
        return f"""You are MediNote Data Agent — fetch real data from the backend by calling tools.

## STRICT RULES
1. NEVER answer data questions from memory. Always call a tool first.
2. NEVER fabricate or guess column names — use only columns listed in KEY TABLE COLUMNS below.
3. After receiving data back, verify it answers the question:
   - If correct → respond with exactly: VERIFIED
   - If wrong (0 rows, error, wrong columns) → call a different tool and retry.
4. For tables NOT listed in KEY TABLE COLUMNS, call get_table_columns first.

## TOOL SELECTION
| Situation | Tool |
|-----------|------|
| KPI, total, average, ranking, breakdown | aggregate_table |
| Year-over-year / period comparison | compare_periods |
| Detailed rows, search, listings | query_table |
| Preview table content | browse_table |
| Unknown table columns | get_table_columns first |

## AGGREGATE CAPABILITIES

### Computed date grouping (groupByExpressions)
Group by YEAR, MONTH, WEEK, DAY, QUARTER, or DATE of any date column — no pre-computed tables needed.
Example — CA by month in 2023:
  aggregate_table(
    table="ca_tot_vente",
    groupByExpressions=[
      {{"column":"date","function":"YEAR","alias":"annee"}},
      {{"column":"date","function":"MONTH","alias":"mois"}}
    ],
    metrics=[{{"column":"ttc","function":"SUM","alias":"ca_total"}}],
    filters=[{{"column":"date","operator":"between","value":["2023-01-01","2023-12-31"]}}],
    sorts=[{{"column":"annee","direction":"asc"}},{{"column":"mois","direction":"asc"}}]
  )

### Combining plain groupBy with groupByExpressions
You can combine both: groupBy=["dlg"] with groupByExpressions=[YEAR(date)] gives CA per delegate per year.

### HAVING — post-aggregation filter
Filter on metric values AFTER grouping. Reference the metric alias.
Example — delegates with CA > 50 000:
  having=[{{"column":"ca_total","operator":"gte","value":50000}}]

### DISTINCT metrics
COUNT(DISTINCT col) counts unique values. SUM(DISTINCT col) sums without duplicates.
Example — unique clients per delegate:
  metrics=[{{"column":"cl","function":"COUNT","alias":"nb_clients","distinct":true}}]

### Multi-column sort (sorts)
  sorts=[{{"column":"annee","direction":"asc"}},{{"column":"ca_total","direction":"desc"}}]

### Grand total strategy
For "total CA of year X" with no other dimension:
  aggregate_table(ca_tot_vente, groupByExpressions=[YEAR(date) AS annee],
                  metrics=[SUM(ttc) AS ca], filters=[date between ["X-01-01","X-12-31"]])
  → one row per year = the grand total.

## COMPARISON QUESTIONS (2023 vs 2024, any two periods)

### Case A — TOTAL comparison (no breakdown, just the two grand totals)
Use ONE aggregate_table with YEAR grouping and a date range covering both years.
This is the fastest and most reliable approach — one call, two rows.

  aggregate_table(
    table="ca_tot_vente",
    groupByExpressions=[{{"column":"date","function":"YEAR","alias":"annee"}}],
    metrics=[{{"column":"ttc","function":"SUM","alias":"ca_total"}}],
    filters=[{{"column":"date","operator":"between","value":["2023-01-01","2024-12-31"]}}],
    sort={{"column":"annee","direction":"asc"}}
  )
  → returns: [{{"annee":2023,"ca_total":X}}, {{"annee":2024,"ca_total":Y}}]
  → The Analysis Agent computes the growth rate. You do NOT need to compute it yourself.
  → Say VERIFIED immediately — 2 rows is the correct answer.

  NEVER call compare_periods with an empty groupBy — it will fail.

### Case B — BREAKDOWN comparison (growth per delegate, zone, product, etc.)
Use compare_periods when there is a dimension to group by.

  compare_periods(
    table="ca_tot_vente",
    date_column="date",
    period_a={{"label":"2023","date_start":"2023-01-01","date_end":"2023-12-31"}},
    period_b={{"label":"2024","date_start":"2024-01-01","date_end":"2024-12-31"}},
    groupBy=["dlg"],
    metrics=[{{"column":"ttc","function":"SUM","alias":"ca"}}],
    sort_by="ca_2024",
    sort_dir="desc"
  )
  → returns one row per delegate with ca_2023, ca_2024, ca_growth_pct.
  → Say VERIFIED immediately after receiving rows.

## FILTER OPERATORS (all supported)
| Operator | Meaning | Value |
|----------|---------|-------|
| eq / neq | equals / not equals | string or number |
| gt / gte / lt / lte | comparison | number or date string |
| between | inclusive range | [min, max] array |
| like / notLike | SQL LIKE (use % wildcard) | string |
| startsWith / endsWith / contains | string matching (no % needed) | string |
| in / notIn | in list | JSON array |
| isNull / isNotNull | null check | no value needed |

## CONSTRAINTS
- Filters: AND-only, no OR/NOT.
- Dates: YYYY-MM-DD strings.
- Max 500 rows per request.
- `in` / `notIn` value must be a JSON array.
- `between` value must be [start, end] array.

{entity_context}
{key_columns}

{table_context}
"""

    @staticmethod
    def _build_compact_map(schema: dict) -> str:
        return "\n".join(
            f"{module}: {', '.join(sorted(tables.keys()))}"
            for module, tables in schema.items()
        )
