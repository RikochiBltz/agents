# MediNote AI — Multi-Agent CRM System
### Full Technical Overview

---

## 1. What is MediNote AI?

MediNote AI is a **multi-agent conversational system** built on top of a pharmaceutical sales CRM. It allows field delegates, managers, and analysts to interact with company data and tools using natural language — in French or English.

The system connects to a **Spring Boot backend** (port 8081) backed by a **MySQL database** (`vital`) containing 129 tables across 9 business modules. Instead of writing SQL or navigating dashboards, users simply ask questions and the system routes them to the right agent automatically.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          USER INPUT                                  │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                                  │
│                      gpt-oss:20b-cloud                               │
│   Routes to Pipeline 1, 2, or 3. Rejects out-of-scope questions.   │
└────────────┬────────────────┬────────────────────┬──────────────────┘
             │                │                    │
             ▼                ▼                    ▼
     Pipeline 1         Pipeline 2           Pipeline 3
  ┌────────────┐      ┌────────────┐      ┌────────────┐
  │ Data Agent │      │   Report   │      │   Doctor   │
  │ DeepSeek   │      │   Agent    │      │   Agent    │
  │671b-cloud  │      │gpt-oss:20b │      │llama3.1:8b │
  └─────┬──────┘      └─────┬──────┘      └─────┬──────┘
        │                   │                    │
        ▼                   │                    │
  ┌────────────┐            │                    │
  │ KPI Agent  │            │                    │
  │gpt-oss:20b │            │                    │
  └─────┬──────┘            │                    │
        │                   │                    │
        ▼                   │                    │
  ┌────────────┐            │                    │
  │  Analysis  │            │                    │
  │   Agent    │            │                    │
  │gpt-oss:20b │            │                    │
  └─────┬──────┘            │                    │
        │                   │                    │
        └───────────────────┴────────────────────┘
                              │
                              ▼
                         RESPONSE
```

All LLMs are served locally via **Ollama** using an OpenAI-compatible API at `http://localhost:11434/v1`. No data leaves the local infrastructure.

---

## 3. The Orchestrator

**Model:** `gpt-oss:20b-cloud`

The Orchestrator is the entry point for every user message. It uses **tool calling** (forced function call) to make a structured routing decision. It never responds with plain text.

### What it does

1. **Scope check** — Rejects questions unrelated to the CRM (general knowledge, jokes, programming help)
2. **Pipeline selection** — Routes to one of three pipelines
3. **Query clarification** — Rewrites ambiguous questions (resolves relative dates, clarifies intent)
4. **Brief generation** — Produces `data_query` and `analysis_spec` for Pipeline 1 agents

### Routing rules

| Trigger | Pipeline |
|---|---|
| Data queries, KPIs, rankings, trends, comparisons | Pipeline 1 |
| Visit report writing, product Q&A, report evaluation | Pipeline 2 |
| Doctor profile lookup, specialty product recommendations | Pipeline 3 |

### Rejection examples
- "What is the capital of France?" → rejected
- "Write me a poem" → rejected
- "Help me fix this Python bug" → rejected

---

## 4. Pipeline 1 — Data & Analytics

```
Orchestrator → DataAgent → KPI Agent → Analysis Agent → Response
```

Used for: all data questions — totals, rankings, trends, comparisons, listings.

---

### 4.1 Data Agent

**Model:** `deepseek-v3.1:671b-cloud`

The DataAgent is the most sophisticated agent in the system. It has access to the Spring Boot backend through **7 tools** and executes a multi-round tool-calling loop to fetch the right data.

#### Tool loop

```
Round 1:  LLM decides which tool to call
Round N:  Tool result returned → LLM evaluates → calls next tool or says VERIFIED
VERIFIED: Raw result emitted → exits loop
```

Maximum 10 rounds. On the last round, tool calling is disabled and the LLM must respond.

#### Available tools

| Tool | Purpose |
|---|---|
| `search_schema` | Search table/column names by keyword |
| `get_table_columns` | Get exact column list for a table |
| `list_modules` | List all 9 database modules |
| `list_tables` | List tables in a module |
| `query_table` | Raw row fetch with filters and sort |
| `aggregate_table` | GROUP BY with metrics, HAVING, computed date expressions |
| `compare_periods` | Side-by-side period comparison with growth % |
| `browse_table` | Preview table contents |

#### Aggregate capabilities

The `aggregate_table` tool supports advanced grouping:

```json
{
  "table": "ca_tot_vente",
  "groupByExpressions": [
    {"column": "date", "function": "YEAR",  "alias": "annee"},
    {"column": "date", "function": "MONTH", "alias": "mois"}
  ],
  "metrics": [
    {"column": "ttc", "function": "SUM", "alias": "ca_total"}
  ],
  "having": [{"column": "ca_total", "operator": "gte", "value": 10000}],
  "sorts": [{"column": "annee", "direction": "asc"}]
}
```

Supported date functions: `YEAR`, `MONTH`, `WEEK`, `DAY`, `QUARTER`, `DATE`

#### Filter operators (16 total)

| Operator | Example |
|---|---|
| `eq`, `neq` | equals / not equals |
| `gt`, `gte`, `lt`, `lte` | numeric / date comparison |
| `between` | `["2024-01-01", "2024-12-31"]` |
| `like`, `notLike` | SQL LIKE with `%` wildcard |
| `startsWith`, `endsWith`, `contains` | string matching |
| `in`, `notIn` | `["value1", "value2"]` |
| `isNull`, `isNotNull` | null checks |

#### Period comparison

For "CA 2023 vs 2024" queries, the DataAgent chooses one of two strategies:

- **Case A (grand total):** One `aggregate_table` call with `YEAR(date)` grouping, returns 2 rows
- **Case B (breakdown):** `compare_periods` tool, returns one row per entity with `metric_2023`, `metric_2024`, `metric_growth_pct`

#### RAG-assisted table discovery

Before calling the LLM, the DataAgent runs a **FAISS-based RAG** built from the system's data dictionary PDF. It retrieves the top 5 most relevant table descriptions and injects them into the system prompt — reducing `search_schema` calls and speeding up table selection.

---

### 4.2 KPI Agent

**Model:** `gpt-oss:20b-cloud`

The KPI Agent sits between the DataAgent and the Analysis Agent. It receives raw data and computes structured **Key Performance Indicators** before the Analysis Agent interprets them.

#### What it computes

- **Growth rates** — year-over-year and period-over-period percentage changes
- **Rankings** — ordinal position of each entity (delegate, zone, product) within their group
- **Running totals** — cumulative sums for trend charts
- **Deviation from average** — how far each entity sits above or below the group mean
- **Target attainment** — percentage of quota achieved (when budget data is available)

#### Why it exists

The DataAgent returns raw aggregated data — sums, counts, grouped rows. Without a dedicated computation layer, the Analysis Agent would have to infer growth rates from raw numbers mid-narrative, which introduces inconsistencies. The KPI Agent normalises and enriches the data into a clean, computation-ready structure before any narrative is generated.

#### Output format

The KPI Agent appends computed fields to each data row:
```json
{
  "delegate": "AHMED BEN ALI",
  "ca_2023": 820000,
  "ca_2024": 945000,
  "growth_pct": 15.24,
  "rank": 2,
  "vs_avg_pct": 12.7
}
```

This enriched result is what the Analysis Agent receives.

---

### 4.3 Analysis Agent

**Model:** `gpt-oss:20b-cloud`

The Analysis Agent receives the KPI-enriched data and produces a **structured narrative** answering the user's question.

#### Output structure (always two sections)

1. **Direct answer** — leads with the key number or finding; answers the user's question in the first sentence
2. **Trend & insight** — identifies direction, top/bottom performers, anomalies, and growth rankings

#### Rules enforced

- Stays in the user's original language (French stays French)
- Uses exact numbers from the data — no rounding without explicit formatting
- 3–6 bullet points or two short paragraphs maximum
- Never repeats raw rows — works from computed KPIs
- Flags when data is partial (truncated at 100 rows)

---

## 5. Pipeline 2 — Visit Report Assistant

```
Orchestrator → Report Agent → Response
```

Used for: field visit report writing assistance, product scientific Q&A.

---

### 5.1 Report Agent

**Model:** `gpt-oss:20b-cloud`

The Report Agent helps pharmaceutical field delegates write, improve, and evaluate their post-visit reports.

#### Intent detection (7 intents)

| Intent | Trigger | Output |
|---|---|---|
| `reformulate` | Raw visit notes | Professional structured report |
| `structure` | "What's the structure of a report?" | Report template |
| `missing_points` | Incomplete draft | List of missing sections |
| `evaluate` | Complete draft | Quality score + feedback |
| `example` | "Give me an example" | Full sample report |
| `technical_help` | Scientific questions | Product-backed technical content |
| `question_answer` | Product Q&A | Dosage, indication, composition |

#### Product RAG (FAISS)

The Report Agent has access to a **FAISS vector index** built from 22 product presentation files (PPTXs). When a user asks about a specific product or needs technical enrichment for a report, the RAG retrieves the relevant product sheets and injects them into the prompt.

- Embedding model: `sentence-transformers/all-MiniLM-L6-v2`
- Index: `rag/faiss_index/catalog.index`
- Graceful degradation if FAISS not installed

#### Language detection

The Report Agent detects whether the user is writing in French or English (including Tunisian dialect markers) and responds in the same language.

---

## 6. Pipeline 3 — Doctor Information

```
Orchestrator → Doctor Agent → Response
```

Used for: doctor profile lookup, specialty-based product recommendations.

---

### 6.1 Doctor Agent

**Model:** `llama3.1:8b`

The Doctor Agent answers questions about specific doctors using a local in-memory registry loaded from `doctors.csv` (31,169 doctors from the Tunisian national medical registry).

#### Entity RAG

Unlike FAISS-based RAGs, the Doctor Agent uses a **token-overlap entity index** — no ML dependencies, zero startup time, sub-5ms query latency.

- **Doctors index:** 31,169 records — Nom, Prénom, Spécialité, Ville, CROM, N°Ordre
- **Products index:** 113 products — nom, forme, catégorie, indications
- **Scoring:** exact token match (+2) + 4-character prefix match (+1)

#### Specialty → product mapping

When a doctor's specialty is identified, the Doctor Agent automatically maps it to relevant products using a 20-specialty expansion dictionary:

| Specialty | Recommended products |
|---|---|
| Cardiologie | Levure de Riz Rouge, Coenzyme Q10, Lécithine de Soja |
| Pédiatrie | Full PEDIAKIDS range (27 products) |
| Gynécologie | VITONIC Grossesse, Conception, Meno, Allaitement, Fertilité |
| Pneumologie | Plantexil, Planthiol, Pulmax, PEDIAKIDS respiratory |
| Dermatologie | UNIDERM range, PHYTOPHANE, TC2000 |
| Psychiatrie | Ashwagandha, Millepertuis, Magnésium |
| Médecine générale | Gelée Royale, VITONIC Tonus, Spiruline |
| Stomatologie | Full PHYTOL oral hygiene range |

#### Why a small local model?

The Doctor Agent does not reason about complex data — it formats pre-retrieved registry information into a clear response. A 8B parameter local model is sufficient for this formatting task and responds in 1–2 seconds without any DB queries.

---

## 7. Data Sources

| Source | Contents | Used by |
|---|---|---|
| MySQL `vital` DB (port 8081) | 129 tables, 9 modules — sales, stock, visits, clients, finance, production, animation, delegates, zones | DataAgent via Spring Boot API |
| `vital_dictionnaire_donnees_complet.pdf` | Data dictionary with table and column descriptions | DataAgent RAG (FAISS) |
| `doctors.csv` | 31,169 Tunisian doctors — name, specialty, city, CROM, order number | Doctor Agent entity index |
| `prod_vital.json` | 113 company products across 10 categories — indications, composition, usage | Doctor Agent + Report Agent |
| 22 product PPTXs | Full product presentations for scientific content | Report Agent FAISS RAG |

---

## 8. Tech Stack

| Component | Technology |
|---|---|
| LLM inference | Ollama (local) with OpenAI-compatible API |
| DataAgent model | DeepSeek V3.1 671B (cloud-routed via Ollama) |
| All other agents | GPT-OSS 20B (cloud-routed via Ollama) |
| Doctor Agent | LLaMA 3.1 8B (local) |
| Vector search (table RAG) | FAISS + nomic-embed-text |
| Vector search (product RAG) | FAISS + sentence-transformers/all-MiniLM-L6-v2 |
| Entity search (doctor/product) | In-memory token overlap — no ML |
| Backend API | Spring Boot (Java) on port 8081 |
| Database | MySQL — `vital` schema |
| CLI interface | Python + Rich |
| Authentication | JWT via Spring Boot — all queries scoped to user role |

---

## 9. Database Modules

| Module | Description | Key tables |
|---|---|---|
| VENTES | Daily and monthly sales transactions | `ca_tot_vente`, `ca_prd_day`, `ca_prd_month` |
| PRODUITS_STOCK | Stock levels, production, entries/exits | `art_stock_day`, `art_prod_day`, `art_entre_sortie` |
| ANIMATION | Field visit sessions and products presented | `annimation_fiches`, `annimation_fiches_produits`, `annimation_ventes` |
| FINANCE | Invoices, payments, balances (admin/staff) | `bl_fact`, `cl_reglement`, `cl_reliquat` |
| BUDGET | Budget tracking and consumption | `budget_conso` |
| ZONES | Geographic zone definitions | zone tables |
| DELEGATES | Sales delegate registry | delegate tables |
| CLIENTS | Client profiles and outstanding balances | `cl_reliquat_dlg` |
| GAMMES | Product families and lines | gamme tables |

---

## 10. Query Examples by Pipeline

### Pipeline 1 — Data queries

| Question | Strategy | Rounds |
|---|---|---|
| "CA total 2024" | `aggregate_table` + `YEAR(date)` | 1 |
| "Top 5 délégués par CA 2023" | `aggregate_table` + `groupBy dlg` | 1–2 |
| "Croissance CA 2023 vs 2024 par délégué" | `compare_periods` | 1 |
| "Évolution mensuelle des ventes 2024" | `aggregate_table` + `YEAR`+`MONTH` | 1–2 |
| "Stock actuel produit Omega 3" | `search_schema` → `query_table` | 2–3 |
| "Délégués avec CA > 500 000" | `aggregate_table` + `having` | 1–2 |

### Pipeline 2 — Report writing

| Question | Intent | Output |
|---|---|---|
| "Reformule mes notes: cardiologue, Omega 3, intéressé" | `reformulate` | Full professional report |
| "Qu'est-ce qui manque dans mon rapport?" | `missing_points` | Checklist of gaps |
| "Quel est le dosage du Plantyl?" | `question_answer` | Dosage + RAG product sheet |
| "Évalue ce rapport: [text]" | `evaluate` | Score + structured feedback |

### Pipeline 3 — Doctor lookup

| Question | Output |
|---|---|
| "Info sur Dr. Syrine Azza Mannoubi" | Profile: specialty, city, CROM, N°Ordre |
| "Qui est Dr. Ben Ali cardiologue Tunis" | Profile + top cardiology product picks |
| "Quels produits pour un pneumologue?" | Plantexil, Planthiol, Pulmax, PEDIAKIDS respiratory |

---

## 11. Security & Scope Control

- All backend calls are authenticated via **JWT** — the user's role determines which tables are accessible (e.g., finance tables restricted to ADMIN/STAFF)
- The Orchestrator **rejects out-of-scope questions** before any agent is invoked — no LLM cycles wasted on irrelevant queries
- All data processing is **local** — LLM inference runs on Ollama, database is on-premise, nothing is sent to external APIs

---

## 12. Response Flow (end to end)

```
User:  "Quels sont les 5 meilleurs délégués par CA en 2024 ?"
  │
  ├─ Orchestrator (4s)
  │    pipeline=1
  │    data_query="Récupère le CA par délégué pour 2024, top 5 décroissant"
  │    analysis_spec="Identifie les 5 meilleurs délégués, commente leur performance"
  │
  ├─ DataAgent round 1 (2s)
  │    aggregate_table(ca_tot_vente, groupBy=[dlg], SUM(ttc), sort desc, size=5)
  │    → 5 rows returned
  │    → VERIFIED
  │
  ├─ KPI Agent (1s)
  │    Computes: rank, growth vs previous period, deviation from group average
  │    Enriches each row with: growth_pct, rank, vs_avg_pct
  │
  ├─ Analysis Agent (2s)
  │    "Le délégué #1 est AHMED BEN SALAH avec 1 245 000 DT (+18.3% vs 2023)..."
  │    Trend: top 3 above average, #4 and #5 below average by >15%
  │
  └─ Response displayed
```

Total time: ~9 seconds for a 5-delegate ranking with KPI enrichment and narrative.
```
