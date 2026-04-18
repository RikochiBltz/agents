"""
MediNote Multi-Agent CLI

Pipelines:
  1 → Orchestrator → DataAgent → Analysis Agent → Response
  2 → Orchestrator → Report Agent → Response
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.text import Text

import config
from core.backend_client import BackendClient
from core.entity_rag import EntityRAG
from core.rag import TableRAG
from agents.orchestrator import Orchestrator, RoutingDecision
from agents.data_agent import DataAgent, DataResult
from agents.analysis_agent import AnalysisAgent
from agents.report_agent import ReportAgent
from agents.doctor_agent import DoctorAgent

console = Console()

PIPELINE_LABELS = {
    1: ("Orchestrator", "DataAgent", "Analysis Agent", "Response"),
    2: ("Orchestrator", "Report Agent", "Response"),
    3: ("Orchestrator", "Doctor Agent", "Response"),
}

TOOL_LABELS = {
    "aggregate_table":   ("SUM/GROUP", "yellow"),
    "compare_periods":   ("COMPARE",   "green"),
    "query_table":       ("QUERY",     "blue"),
    "browse_table":      ("BROWSE",    "blue"),
    "get_table_columns": ("COLUMNS",   "dim"),
    "list_tables":       ("TABLES",    "dim"),
    "list_modules":      ("MODULES",   "dim"),
    "search_schema":     ("SEARCH",    "dim"),
}

HELP_TEXT = """
[bold]Commands[/bold]
  [cyan]/schema[/cyan]       — Print the full schema
  [cyan]/tables[/cyan]       — List all table names
  [cyan]/modules[/cyan]      — List all modules
  [cyan]/reload[/cyan]       — Reload schema from backend
  [cyan]/rebuild-rag[/cyan]  — Rebuild RAG index from PDF
  [cyan]/clear[/cyan]        — Clear screen
  [cyan]/help[/cyan]         — Show this message
  [cyan]/exit[/cyan]         — Quit
"""


# ── Startup helpers ───────────────────────────────────────────────────

def startup_banner():
    console.print(Panel(
        "[bold cyan]MediNote Multi-Agent CLI[/bold cyan]\n"
        f"[dim]Backend     : {config.BACKEND_URL}[/dim]\n"
        f"[dim]DataAgent   : {config.LLM_MODEL}[/dim]\n"
        f"[dim]Orchestrator: {config.ORCHESTRATOR_MODEL}[/dim]\n"
        "[dim]Type /help for commands[/dim]",
        expand=False,
    ))


def connect_backend() -> BackendClient:
    client = BackendClient()
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        email    = Prompt.ask("[bold]Email[/bold]")
        password = Prompt.ask("[bold]Password[/bold]", password=True)
        try:
            with console.status("[yellow]Authenticating...[/yellow]"):
                role = client.login(email, password)
            console.print(
                f"[green]Logged in[/green] — [bold]{email}[/bold] [dim]({role})[/dim]"
            )
            return client
        except Exception as e:
            remaining = max_attempts - attempt
            if remaining > 0:
                console.print(
                    f"[red]Login failed:[/red] {e}  "
                    f"[dim]({remaining} attempt{'s' if remaining > 1 else ''} left)[/dim]"
                )
            else:
                console.print(f"[red]Login failed:[/red] {e}")
    console.print("[red]Too many failed attempts. Exiting.[/red]")
    sys.exit(1)


def setup_rag() -> TableRAG | None:
    pdf = config.PDF_PATH
    if not Path(pdf).exists():
        console.print(f"[dim]PDF not found ({pdf}) — RAG disabled[/dim]")
        return None
    rag = TableRAG()
    if rag.is_built:
        console.print("[green]RAG index ready[/green] [dim](cached)[/dim]")
        return rag
    with console.status("[yellow]Building RAG index from PDF...[/yellow]"):
        try:
            n = rag.build(pdf)
            console.print(f"[green]RAG index built:[/green] {n} tables")
        except Exception as e:
            console.print(f"[red]RAG build failed: {e}[/red]")
            return None
    return rag


def _setup_entity_rag() -> EntityRAG | None:
    doctors_path  = config.ENTITY_DOCTORS_CSV
    products_path = config.ENTITY_PRODUCTS_JSON
    if not Path(doctors_path).exists() and not Path(products_path).exists():
        console.print("[dim]Entity RAG files not found — entity lookup disabled[/dim]")
        return None
    with console.status("[yellow]Loading entity index (doctors + products)...[/yellow]"):
        try:
            rag = EntityRAG(doctors_csv=doctors_path, products_json=products_path)
            console.print(
                f"[green]Entity index ready:[/green] "
                f"{rag.doctor_count} doctors, {rag.product_count} products"
            )
            return rag
        except Exception as e:
            console.print(f"[red]Entity RAG load failed: {e}[/red]")
            return None


def load_schema(agent: DataAgent) -> None:
    with console.status("[yellow]Loading schema...[/yellow]"):
        agent.load_schema()
    n = sum(len(t) for t in agent._schema.values())
    console.print(f"[green]Schema loaded:[/green] {len(agent._schema)} modules, {n} tables")


# ── Pipeline execution ────────────────────────────────────────────────

def run_pipeline(
    question: str,
    orchestrator: Orchestrator,
    data_agent: DataAgent,
    analysis_agent: AnalysisAgent,
    report_agent: ReportAgent,
    doctor_agent: DoctorAgent | None = None,
) -> None:
    total_start = time.perf_counter()

    # ── Step 1: Orchestrator ──────────────────────────────────────────
    console.print()
    with console.status(
        f"[yellow]Orchestrator ({config.ORCHESTRATOR_MODEL}) routing...[/yellow]",
        spinner="dots",
    ):
        t0 = time.perf_counter()
        try:
            routing = orchestrator.route(question)
        except Exception as e:
            console.print(f"[red]Orchestrator error: {e}[/red]")
            return
        orchestrator_ms = int((time.perf_counter() - t0) * 1000)

    if routing.rejected:
        console.print(Panel(
            f"[yellow]{routing.rejection_message}[/yellow]",
            title="[yellow]hors périmètre[/yellow]",
            border_style="yellow",
            expand=False,
        ))
        return

    _print_routing(routing, orchestrator_ms)

    # ── Step 2: Execute pipeline ──────────────────────────────────────
    final: DataResult

    if routing.pipeline == 1:
        final = _run_data_pipeline(routing, data_agent, analysis_agent, orchestrator_ms)
    elif routing.pipeline == 2:
        t0 = time.perf_counter()
        with console.status(
            f"[magenta]Report Agent ({config.REPORT_MODEL})...[/magenta]",
            spinner="dots",
        ):
            final = report_agent.process(routing.raw_question)
        report_ms = int((time.perf_counter() - t0) * 1000)
        final.timing = [
            ("orchestrator", "Orchestrator", orchestrator_ms),
            ("report",       "Report Agent", report_ms),
        ]
    else:  # pipeline == 3
        t0 = time.perf_counter()
        with console.status(
            f"[blue]Doctor Agent ({config.DOCTOR_MODEL})...[/blue]",
            spinner="dots",
        ):
            final = doctor_agent.process(routing.raw_question) if doctor_agent else DataResult(error="Doctor Agent not available")
        doctor_ms = int((time.perf_counter() - t0) * 1000)
        final.timing = [
            ("orchestrator", "Orchestrator", orchestrator_ms),
            ("doctor",       "Doctor Agent", doctor_ms),
        ]

    # ── Step 3: Display result ────────────────────────────────────────
    total_ms = int((time.perf_counter() - total_start) * 1000)
    _display_result(final, routing, total_ms)


def _run_data_pipeline(
    routing: RoutingDecision,
    data_agent: DataAgent,
    analysis_agent: AnalysisAgent,
    orchestrator_ms: int = 0,
) -> DataResult:
    """Run DataAgent → Analysis Agent for pipeline 1."""
    rag_indicator = ""
    timing: list[tuple] = []
    answer_parts: list[str] = []
    llm_round = 0
    query_detail: dict | None = None
    data_result = DataResult(clarified_question=routing.data_query)

    with console.status(
        f"[cyan]DataAgent ({config.LLM_MODEL})...[/cyan]",
        spinner="dots",
    ) as status:
        for chunk in data_agent.stream(routing.data_query):

            if chunk.startswith("__rag__:"):
                parts = chunk.split(":", 2)
                count = int(parts[1])
                tables = parts[2] if len(parts) > 2 else ""
                rag_indicator = (
                    f"[green]RAG ✓[/green] [dim]{tables}[/dim]"
                    if count > 0 else "[dim]RAG — not used[/dim]"
                )
                data_result.rag_tables = [t for t in tables.split(",") if t]

            elif chunk.startswith("__timing__:llm:"):
                llm_round += 1
                ms = int(chunk.split(":")[2])
                timing.append(("llm", f"DataAgent LLM round {llm_round}", ms))

            elif chunk.startswith("__timing__:tool:"):
                p = chunk.split(":", 3)
                ms = int(p[3])
                timing.append(("tool", p[2], ms))

            elif chunk.startswith("__tool_call__:"):
                p = chunk.strip().split(":", 2)
                tool_name = p[1] if len(p) > 1 else "?"
                try:
                    args = json.loads(p[2]) if len(p) > 2 else {}
                except Exception:
                    args = {}
                label, color = TOOL_LABELS.get(tool_name, (tool_name, "white"))
                table = args.get("table", args.get("keyword", ""))
                suffix = f" → [italic]{table}[/italic]" if table else ""
                status.update(f"[{color}][{label}][/{color}]{suffix}")

            elif chunk.startswith("__query_detail__:"):
                # keep only the last query detail (the one that produced final data)
                rest = chunk[len("__query_detail__:"):]
                sep = rest.index(":")
                try:
                    query_detail = {"tool": rest[:sep], "args": json.loads(rest[sep+1:])}
                except Exception:
                    pass

            elif chunk.startswith("__raw_result__:"):
                try:
                    data_result.data = json.loads(chunk[len("__raw_result__:"):])
                except Exception:
                    data_result.error = "Failed to parse backend response"

            elif not chunk.startswith("__"):
                answer_parts.append(chunk)

    if data_result.data is None and answer_parts:
        data_result.error = "".join(answer_parts).strip()

    # Prepend orchestrator, then DataAgent events
    data_result.timing = [("orchestrator", "Orchestrator", orchestrator_ms)] + timing

    if rag_indicator:
        console.print(rag_indicator)

    # Show query detail
    if query_detail:
        _print_query_detail(query_detail)

    # Analysis Agent interprets the data
    t0 = time.perf_counter()
    with console.status(f"[magenta]Analysis Agent ({config.ANALYSIS_MODEL})...[/magenta]", spinner="dots"):
        data_result = analysis_agent.process(
            data_result,
            analysis_spec=routing.analysis_spec,
            question=routing.raw_question,
        )
    data_result.timing.append(("analysis", "Analysis Agent", int((time.perf_counter() - t0) * 1000)))

    return data_result


# ── Display helpers ───────────────────────────────────────────────────

def _print_query_detail(detail: dict) -> None:
    """Show the exact API call the DataAgent made."""
    tool = detail.get("tool", "")
    args = detail.get("args", {})
    table = args.get("table", "")

    lines = [f"  [dim]Query  : {tool}({table})[/dim]"]

    if args.get("filters"):
        for f in args["filters"]:
            lines.append(f"  [dim]  filter: {f['column']} {f['operator']} {f['value']}[/dim]")

    if args.get("groupBy"):
        lines.append(f"  [dim]  groupBy: {args['groupBy']}[/dim]")

    if args.get("metrics"):
        for m in args["metrics"]:
            lines.append(f"  [dim]  metric: {m['function']}({m['column']}) as {m['alias']}[/dim]")

    if args.get("sort"):
        s = args["sort"]
        lines.append(f"  [dim]  sort: {s['column']} {s['direction']}[/dim]")

    for line in lines:
        console.print(line)


def _print_routing(routing: RoutingDecision, orchestrator_ms: int) -> None:
    pipeline_nodes = PIPELINE_LABELS[routing.pipeline]
    path = " → ".join(
        f"[bold cyan]{n}[/bold cyan]" if n == "Orchestrator"
        else f"[yellow]{n}[/yellow]" if n == "DataAgent"
        else f"[dim]{n}[/dim]"
        for n in pipeline_nodes
    )
    console.print(f"  Pipeline [bold]{routing.pipeline}[/bold]:  {path}")
    console.print(f"  [dim]Reason    : {routing.reasoning}[/dim]")
    if routing.data_query:
        console.print(f"  [dim]DataQuery : {routing.data_query}[/dim]")
    if routing.analysis_spec:
        console.print(f"  [dim]Analysis  : {routing.analysis_spec}[/dim]")
    console.print(f"  [dim]Orchestrator took {_fmt_ms(orchestrator_ms)}[/dim]")
    console.print()


def _print_agent_briefs(routing: RoutingDecision) -> None:
    """Print a per-agent summary of what each agent was asked."""
    _ACTIVE  = "[bold green]✓[/bold green]"
    _SKIPPED = "[dim]—[/dim]"

    def brief(spec: str) -> str:
        return f"[dim]{spec}[/dim]" if spec else "[dim italic]no spec[/dim italic]"

    agents: list[tuple[str, str, str]] = []
    agents.append((_ACTIVE, "Orchestrator", f"[dim]{routing.reasoning}[/dim]"))

    if routing.pipeline == 1:
        agents.append((_ACTIVE,  "DataAgent",     brief(routing.data_query)))
        agents.append((_ACTIVE,  "Analysis Agent", brief(routing.analysis_spec)))
    else:
        agents.append((_SKIPPED, "DataAgent",      "[dim italic]skipped[/dim italic]"))
        agents.append((_SKIPPED, "Analysis Agent", "[dim italic]skipped[/dim italic]"))
        agents.append((_ACTIVE,  "Report Agent",   "[dim]generate report[/dim]"))

    lines = [f"  {marker} [bold]{name:<18}[/bold] {b}" for marker, name, b in agents]

    console.print(Panel(
        "\n".join(lines),
        title="[bold]pipeline recap[/bold]",
        border_style="dim",
        expand=False,
    ))


def _display_result(result: DataResult, routing: RoutingDecision, total_ms: int) -> None:
    is_report = routing.pipeline == 2
    if result.error:
        console.print(Panel(
            f"[red]{result.error}[/red]",
            title="[red]error[/red]",
            border_style="red",
            expand=False,
        ))
    elif result.data:
        total_rows = result.data.get("totalRows", -1)
        if total_rows == 0:
            console.print(Panel(
                "[yellow]0 rows returned.[/yellow]\n\n"
                "[dim]Possible causes:[/dim]\n"
                "[dim]• The date/year filter has no matching data[/dim]\n"
                "[dim]• Wrong table selected for this question[/dim]\n"
                "[dim]• The table is empty[/dim]\n\n"
                "[dim]Check the Query detail above to see what filters were applied.[/dim]",
                title="[yellow]empty result[/yellow]",
                border_style="yellow",
                expand=False,
            ))
        else:
            pretty = json.dumps(result.data, indent=2, ensure_ascii=False, default=str)
            console.print(Panel(
                Syntax(pretty, "json", theme="monokai", word_wrap=True),
                title=f"[bold cyan]result[/bold cyan] [dim]({total_rows} rows)[/dim]",
                border_style="cyan",
                expand=False,
            ))
    else:
        console.print("[dim]No data returned.[/dim]")

    # ── Analysis / Report output ──────────────────────────────────────
    if result.analysis:
        if is_report:
            panel_title = f"[bold magenta]rapport[/bold magenta] [dim]({config.REPORT_MODEL})[/dim]"
        else:
            panel_title = f"[bold magenta]analysis[/bold magenta] [dim]({config.ANALYSIS_MODEL})[/dim]"
        console.print(Panel(
            Markdown(result.analysis),
            title=panel_title,
            border_style="magenta",
            expand=False,
        ))

    # ── Timing timeline ───────────────────────────────────────────────
    _TIMING_COLOR = {
        "orchestrator": "cyan",
        "llm":          "yellow",
        "tool":         "blue",
        "analysis":     "magenta",
        "report":       "magenta",
    }
    if result.timing:
        console.print()
        for kind, label, ms in result.timing:
            color = _TIMING_COLOR.get(kind, "white")
            bar = _time_bar(ms, total_ms)
            console.print(
                f"  [{color}]{label:<40}[/{color}]  {bar}  [bold]{_fmt_ms(ms)}[/bold]"
            )
        console.print(f"  {'─' * 62}")
        console.print(
            f"  [bold white]{'Total':<40}[/bold white]  {'':12}  "
            f"[bold green]{_fmt_ms(total_ms)}[/bold green]"
        )

    # ── Pipeline path recap with per-agent briefs ────────────────────
    console.print()
    _print_agent_briefs(routing)


# ── Slash commands ────────────────────────────────────────────────────

def handle_command(cmd: str, data_agent: DataAgent, rag: TableRAG | None) -> bool:
    cmd = cmd.strip().lower()

    if cmd == "/exit":
        console.print("[dim]Bye.[/dim]")
        sys.exit(0)
    elif cmd == "/clear":
        console.clear()
    elif cmd == "/help":
        console.print(HELP_TEXT)
    elif cmd == "/reload":
        load_schema(data_agent)
    elif cmd == "/schema":
        if not data_agent._schema:
            console.print("[red]Schema not loaded. Try /reload.[/red]")
        else:
            for module, tables in data_agent._schema.items():
                console.print(f"\n[bold cyan]{module}[/bold cyan]")
                for table, cols in tables.items():
                    console.print(f"  [yellow]{table}[/yellow]: {', '.join(c['name'] for c in cols)}")
    elif cmd == "/tables":
        if not data_agent._schema:
            console.print("[red]Schema not loaded.[/red]")
        else:
            all_tables = sorted(t for tables in data_agent._schema.values() for t in tables)
            console.print(", ".join(all_tables))
    elif cmd == "/modules":
        if not data_agent._schema:
            console.print("[red]Schema not loaded.[/red]")
        else:
            for m, t in data_agent._schema.items():
                console.print(f"[cyan]{m}[/cyan] — {len(t)} tables")
    elif cmd == "/rebuild-rag":
        if not rag:
            console.print("[red]RAG not initialised (PDF not found).[/red]")
        else:
            with console.status("[yellow]Rebuilding RAG...[/yellow]"):
                try:
                    n = rag.build(config.PDF_PATH)
                    console.print(f"[green]RAG rebuilt:[/green] {n} tables")
                except Exception as e:
                    console.print(f"[red]{e}[/red]")
    else:
        return False
    return True


# ── Utilities ─────────────────────────────────────────────────────────

def _fmt_ms(ms: int) -> str:
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.2f} s"


def _time_bar(ms: int, total_ms: int) -> str:
    if total_ms == 0:
        return " " * 12
    filled = max(1, round((ms / total_ms) * 12))
    return f"[green]{'█' * filled}{'░' * (12 - filled)}[/green]"


# ── Entry point ───────────────────────────────────────────────────────

def main():
    startup_banner()

    try:
        client = connect_backend()
    except Exception as e:
        console.print(f"[red]Cannot connect to backend: {e}[/red]")
        sys.exit(1)

    rag        = setup_rag()
    entity_rag = _setup_entity_rag()

    orchestrator   = Orchestrator()
    data_agent     = DataAgent(client, rag=rag)
    analysis_agent = AnalysisAgent()
    report_agent   = ReportAgent()
    doctor_agent   = DoctorAgent(entity_rag) if entity_rag else None
    if doctor_agent is None:
        console.print("[yellow]Doctor Agent disabled — entity RAG not loaded[/yellow]")

    try:
        load_schema(data_agent)
    except Exception as e:
        console.print(f"[red]Failed to load schema: {e}[/red]")

    console.print()

    while True:
        try:
            question = Prompt.ask("[bold green]you[/bold green]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye.[/dim]")
            break

        if not question.strip():
            continue

        if question.strip().startswith("/"):
            if not handle_command(question.strip(), data_agent, rag):
                console.print(f"[red]Unknown command: {question.strip()}[/red]")
            console.print()
            continue

        try:
            run_pipeline(
                question,
                orchestrator,
                data_agent,
                analysis_agent,
                report_agent,
                doctor_agent,
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

        console.print()


if __name__ == "__main__":
    main()
