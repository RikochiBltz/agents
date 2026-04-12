"""
workflow/diagram.py

Generates a comprehensive HTML diagram of the MediNote multi-agent pipeline
and opens it in the default browser. No external dependencies — pure stdlib.

Covers:
  - Full architecture overview
  - Pipeline 1: all DataAgent scenarios + tool selection logic
  - Pipeline 2: Report Agent intent flows + FAISS RAG
  - Scope guardrail (rejection path)
  - Backend aggregate capabilities cheat-sheet
"""
import webbrowser
from pathlib import Path

# ── Output choice: browser is best here ──────────────────────────────
# Reasons over static image:
#   • Mermaid.js renders vector diagrams — crisp at any zoom
#   • Zero Python deps (no matplotlib / graphviz / PIL)
#   • Multiple diagrams on one scrollable page with navigation
#   • Readable labels, no layout fighting
# ─────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>MediNote — Multi-Agent Pipeline</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
  :root {
    --bg:       #0f1117;
    --surface:  #1a1d27;
    --border:   #2e3347;
    --text:     #e2e8f0;
    --muted:    #8892a4;
    --orch:     #a78bfa;
    --data:     #f87171;
    --analysis: #34d399;
    --report:   #fbbf24;
    --backend:  #60a5fa;
    --reject:   #fb923c;
    --tag-bg:   #1e2235;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 15px;
    line-height: 1.6;
  }

  /* ── Nav ── */
  nav {
    position: sticky; top: 0; z-index: 100;
    background: #0d1020ee;
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
    display: flex; gap: 4px; padding: 10px 24px;
    flex-wrap: wrap;
  }
  nav a {
    color: var(--muted); text-decoration: none;
    padding: 4px 12px; border-radius: 6px;
    font-size: 13px; font-weight: 500;
    transition: all .15s;
  }
  nav a:hover { background: var(--border); color: var(--text); }
  nav a.active { background: var(--orch); color: #fff; }

  /* ── Layout ── */
  .page { max-width: 1100px; margin: 0 auto; padding: 0 24px 80px; }

  /* ── Hero ── */
  .hero {
    padding: 52px 0 36px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 48px;
  }
  .hero h1 { font-size: 28px; font-weight: 700; margin-bottom: 8px; }
  .hero h1 span { color: var(--orch); }
  .hero p  { color: var(--muted); max-width: 640px; }
  .badge-row { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
  .badge {
    padding: 3px 10px; border-radius: 20px;
    font-size: 12px; font-weight: 600; letter-spacing: .3px;
  }

  /* ── Section ── */
  section { margin-bottom: 64px; scroll-margin-top: 64px; }
  section h2 {
    font-size: 20px; font-weight: 700;
    margin-bottom: 6px; padding-bottom: 10px;
    border-bottom: 1px solid var(--border);
  }
  section h2 .num {
    display: inline-block;
    background: var(--orch); color: #fff;
    width: 26px; height: 26px; border-radius: 50%;
    text-align: center; line-height: 26px;
    font-size: 13px; margin-right: 10px;
  }
  .subtitle { color: var(--muted); margin-bottom: 24px; font-size: 14px; }

  /* ── Diagram card ── */
  .diagram-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 28px 24px;
    margin-bottom: 24px;
    overflow-x: auto;
  }
  .diagram-card h3 {
    font-size: 14px; font-weight: 600;
    color: var(--muted); text-transform: uppercase;
    letter-spacing: .6px; margin-bottom: 20px;
  }
  .diagram-card .mermaid { min-height: 80px; }

  /* ── Two-col grid ── */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 720px) { .grid-2 { grid-template-columns: 1fr; } }

  /* ── Scenario card ── */
  .scenario {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 20px;
  }
  .scenario h4 {
    font-size: 13px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .5px;
    margin-bottom: 10px;
  }
  .scenario ul { padding-left: 18px; color: var(--muted); font-size: 13.5px; }
  .scenario ul li { margin-bottom: 4px; }
  .scenario .tag {
    display: inline-block;
    background: var(--tag-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 11.5px;
    font-family: 'Courier New', monospace;
    color: var(--analysis);
    margin-top: 8px;
    margin-right: 4px;
  }

  /* ── Table ── */
  .ref-table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
  .ref-table th {
    background: var(--tag-bg);
    color: var(--muted);
    text-align: left;
    padding: 10px 14px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .4px;
    text-transform: uppercase;
    border-bottom: 1px solid var(--border);
  }
  .ref-table td {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  .ref-table tr:last-child td { border-bottom: none; }
  .ref-table tr:hover td { background: var(--tag-bg); }
  code {
    background: var(--tag-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 12px;
    color: var(--analysis);
    font-family: 'Courier New', monospace;
  }

  /* ── Legend dots ── */
  .legend { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 20px; }
  .legend-item { display: flex; align-items: center; gap: 7px; font-size: 13px; }
  .dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
</style>
</head>
<body>

<nav id="topnav">
  <a href="#overview"   class="active">Overview</a>
  <a href="#pipeline1"          >Pipeline 1</a>
  <a href="#scenarios-p1"       >P1 Scenarios</a>
  <a href="#pipeline2"          >Pipeline 2</a>
  <a href="#scenarios-p2"       >P2 Scenarios</a>
  <a href="#tools"              >Tool Reference</a>
  <a href="#aggregate"          >Aggregate API</a>
</nav>

<div class="page">

<!-- ── HERO ────────────────────────────────────────────────── -->
<div class="hero">
  <h1>MediNote <span>Multi-Agent Pipeline</span></h1>
  <p>
    A pharmaceutical sales CRM powered by a multi-agent AI system.
    The Orchestrator routes every question to the right pipeline;
    agents fetch, compute, and explain data from 129 MySQL tables.
  </p>
  <div class="badge-row">
    <span class="badge" style="background:#2d1f6e;color:var(--orch)">Orchestrator · gpt-oss:20b-cloud</span>
    <span class="badge" style="background:#3d1515;color:var(--data)">DataAgent · deepseek-v3.1:671b-cloud</span>
    <span class="badge" style="background:#0f2e22;color:var(--analysis)">Analysis · gpt-oss:20b-cloud</span>
    <span class="badge" style="background:#2e2000;color:var(--report)">Report · gpt-oss:20b-cloud</span>
    <span class="badge" style="background:#0d1f3a;color:var(--backend)">Backend · Spring Boot · MySQL</span>
  </div>
</div>


<!-- ══════════════════════════════════════════════════════════
     SECTION 1 — OVERVIEW
══════════════════════════════════════════════════════════ -->
<section id="overview">
  <h2><span class="num">1</span>Architecture Overview</h2>
  <p class="subtitle">Full request lifecycle from user input to response.</p>

  <div class="legend">
    <div class="legend-item"><div class="dot" style="background:var(--orch)"></div>Orchestrator</div>
    <div class="legend-item"><div class="dot" style="background:var(--data)"></div>DataAgent</div>
    <div class="legend-item"><div class="dot" style="background:var(--analysis)"></div>Analysis Agent</div>
    <div class="legend-item"><div class="dot" style="background:var(--report)"></div>Report Agent</div>
    <div class="legend-item"><div class="dot" style="background:var(--backend)"></div>Backend / External</div>
    <div class="legend-item"><div class="dot" style="background:var(--reject)"></div>Rejection</div>
  </div>

  <div class="diagram-card">
    <h3>Full Pipeline</h3>
    <div class="mermaid">
flowchart TD
    IN([" 💬 User Question "]):::input

    IN --> ORCH["🧭 Orchestrator\ngpt-oss:20b-cloud"]:::orch

    ORCH -->|"❌ Off-topic / general\nknowledge"| REJ([" Rejected — out of scope "]):::reject

    ORCH -->|"📊 Pipeline 1\nData · KPI · Analytics"| DA["🤖 DataAgent\ndeepseek-v3.1:671b-cloud\nup to 10 tool-call rounds"]:::data

    ORCH -->|"📋 Pipeline 2\nVisit report assistance"| RA["📝 Report Agent\ngpt-oss:20b-cloud"]:::report

    DA <-->|"REST API calls\naggregate · query · compare"| BE[("🗄️ MediNote Backend\nSpring Boot · MySQL\n129 tables · 9 modules")]:::backend

    DA -->|"VERIFIED ✓\ndata confirmed"| ANA["🔍 Analysis Agent\ngpt-oss:20b-cloud"]:::analysis

    RA <-->|"semantic search\ntop-k chunks"| FAISS[("📚 FAISS Catalog RAG\nsentence-transformers\n22 product PPTXs")]:::backend

    ANA --> OUT1([" ✅ Answer + Trend Analysis "]):::output
    RA  --> OUT2([" ✅ Report / Reformulation "]):::output
    REJ --> STOP([" ⛔ Polite rejection "]):::reject

    classDef input    fill:#1e2040,stroke:#6c63ff,color:#c4b5fd
    classDef orch     fill:#2d1f6e,stroke:#a78bfa,color:#ede9fe
    classDef data     fill:#3d1515,stroke:#f87171,color:#fecaca
    classDef analysis fill:#0f2e22,stroke:#34d399,color:#a7f3d0
    classDef report   fill:#2e2000,stroke:#fbbf24,color:#fef3c7
    classDef backend  fill:#0d1f3a,stroke:#60a5fa,color:#bfdbfe
    classDef output   fill:#0a2a1a,stroke:#34d399,color:#a7f3d0
    classDef reject   fill:#2e1206,stroke:#fb923c,color:#fed7aa
    </div>
  </div>
</section>


<!-- ══════════════════════════════════════════════════════════
     SECTION 2 — PIPELINE 1 DETAIL
══════════════════════════════════════════════════════════ -->
<section id="pipeline1">
  <h2><span class="num">2</span>Pipeline 1 — DataAgent Internal Flow</h2>
  <p class="subtitle">How the DataAgent discovers tables, selects tools, and confirms data before passing to Analysis.</p>

  <div class="diagram-card">
    <h3>DataAgent Tool-Call Loop</h3>
    <div class="mermaid">
flowchart TD
    START(["Question from Orchestrator"]):::input
    RAG["RAG lookup\nfind relevant tables\nfrom PDF documentation"]:::backend
    PROMPT["Build system prompt\n+ inject key table columns\n+ RAG context"]:::orch
    LLM["LLM call\ndeepseek-v3.1:671b-cloud"]:::data

    LLM -->|"tool_call"| DISPATCH{"Dispatch\ntool"}:::orch
    LLM -->|"text: VERIFIED"| VERIFY["Emit __raw_result__\n→ Analysis Agent"]:::analysis
    LLM -->|"text: error / explanation\n(round 10 reached)"| ERR(["Error or no-data response"]):::reject

    DISPATCH --> T1["search_schema\nfind tables by keyword"]:::backend
    DISPATCH --> T2["get_table_columns\nconfirm exact columns"]:::backend
    DISPATCH --> T3["aggregate_table\nGROUP BY + metrics"]:::backend
    DISPATCH --> T4["compare_periods\nA vs B merger"]:::backend
    DISPATCH --> T5["query_table\nraw filtered rows"]:::backend
    DISPATCH --> T6["browse_table\npreview content"]:::backend

    T1 & T2 & T3 & T4 & T5 & T6 -->|"result + hint\n[N rows — verify or retry]"| LLM

    START --> RAG --> PROMPT --> LLM

    classDef input    fill:#1e2040,stroke:#6c63ff,color:#c4b5fd
    classDef orch     fill:#2d1f6e,stroke:#a78bfa,color:#ede9fe
    classDef data     fill:#3d1515,stroke:#f87171,color:#fecaca
    classDef analysis fill:#0f2e22,stroke:#34d399,color:#a7f3d0
    classDef backend  fill:#0d1f3a,stroke:#60a5fa,color:#bfdbfe
    classDef reject   fill:#2e1206,stroke:#fb923c,color:#fed7aa
    </div>
  </div>
</section>


<!-- ══════════════════════════════════════════════════════════
     SECTION 3 — PIPELINE 1 SCENARIOS
══════════════════════════════════════════════════════════ -->
<section id="scenarios-p1">
  <h2><span class="num">3</span>Pipeline 1 — Query Scenarios</h2>
  <p class="subtitle">How the DataAgent picks the right strategy for each question type.</p>

  <div class="diagram-card">
    <h3>Scenario Decision Tree</h3>
    <div class="mermaid">
flowchart LR
    Q{{"Question\ntype"}}:::orch

    Q -->|"CA 2023 vs 2024\ngrand total"| A["aggregate_table\ngroupByExpressions: YEAR(date)\ndate between 2023–2024\n→ 2 rows, Analysis computes growth"]:::data

    Q -->|"CA 2023 vs 2024\nby delegate / zone"| B["compare_periods\ngroupBy: dlg or zone\n→ merged rows with\nca_2023 · ca_2024 · growth_pct"]:::data

    Q -->|"CA by month\nor by product"| C["aggregate_table\ngroupByExpressions: MONTH(date)\nor groupBy: art / fam\nHAVING / sorts"]:::data

    Q -->|"Top N performers\nwith threshold"| D["aggregate_table\nsorts: desc · size: N\nHAVING: metric ≥ threshold"]:::data

    Q -->|"Raw listings\ndetailed rows"| E["query_table\nfilters · sort · paginate"]:::data

    Q -->|"Unknown table\nor columns"| F["search_schema\nthen get_table_columns"]:::backend

    A & B & C & D --> ANA["Analysis Agent\ndirect answer + trend"]:::analysis
    E --> ANA
    F -->|"schema known"| Q

    classDef orch     fill:#2d1f6e,stroke:#a78bfa,color:#ede9fe
    classDef data     fill:#3d1515,stroke:#f87171,color:#fecaca
    classDef analysis fill:#0f2e22,stroke:#34d399,color:#a7f3d0
    classDef backend  fill:#0d1f3a,stroke:#60a5fa,color:#bfdbfe
    </div>
  </div>

  <div class="grid-2">

    <div class="scenario">
      <h4 style="color:var(--data)">📊 Grand Total Comparison</h4>
      <p style="font-size:13px;color:var(--muted);margin-bottom:10px">
        "CA total 2023 vs 2024"
      </p>
      <ul>
        <li>ONE aggregate_table call</li>
        <li>groupByExpressions: YEAR(date) AS annee</li>
        <li>filters: date between 2023-01-01 / 2024-12-31</li>
        <li>Returns 2 rows — one per year</li>
        <li>Analysis Agent computes growth %</li>
      </ul>
      <span class="tag">aggregate_table</span>
      <span class="tag" style="color:var(--orch)">YEAR(date)</span>
    </div>

    <div class="scenario">
      <h4 style="color:var(--data)">📈 Breakdown Comparison</h4>
      <p style="font-size:13px;color:var(--muted);margin-bottom:10px">
        "Croissance CA par délégué 2023→2024"
      </p>
      <ul>
        <li>compare_periods — requires groupBy</li>
        <li>period_a: 2023-01-01 / 2023-12-31</li>
        <li>period_b: 2024-01-01 / 2024-12-31</li>
        <li>groupBy: ["dlg"] (mandatory)</li>
        <li>Returns: ca_2023 · ca_2024 · ca_growth_pct per delegate</li>
      </ul>
      <span class="tag">compare_periods</span>
      <span class="tag" style="color:var(--orch)">groupBy required</span>
    </div>

    <div class="scenario">
      <h4 style="color:var(--data)">🗓️ Period Breakdown (monthly/quarterly)</h4>
      <p style="font-size:13px;color:var(--muted);margin-bottom:10px">
        "CA par produit par mois 2023"
      </p>
      <ul>
        <li>aggregate_table on ca_tot_vente</li>
        <li>groupBy: ["art"] + groupByExpressions: YEAR + MONTH</li>
        <li>filters: date between full year range</li>
        <li>sorts: annee asc · mois asc · ca desc</li>
      </ul>
      <span class="tag">aggregate_table</span>
      <span class="tag" style="color:var(--orch)">MONTH(date)</span>
      <span class="tag" style="color:var(--orch)">multi-sort</span>
    </div>

    <div class="scenario">
      <h4 style="color:var(--data)">🏆 Rankings with Threshold</h4>
      <p style="font-size:13px;color:var(--muted);margin-bottom:10px">
        "Top 5 délégués avec CA ≥ 100 000"
      </p>
      <ul>
        <li>aggregate_table — groupBy: ["dlg"]</li>
        <li>metrics: SUM(ttc) AS ca_total, COUNT(DISTINCT cl) AS nb_clients</li>
        <li>having: ca_total ≥ 100000</li>
        <li>sort: ca_total desc · size: 5</li>
      </ul>
      <span class="tag">aggregate_table</span>
      <span class="tag" style="color:var(--orch)">HAVING</span>
      <span class="tag" style="color:var(--orch)">DISTINCT</span>
    </div>

  </div>
</section>


<!-- ══════════════════════════════════════════════════════════
     SECTION 4 — PIPELINE 2 DETAIL
══════════════════════════════════════════════════════════ -->
<section id="pipeline2">
  <h2><span class="num">4</span>Pipeline 2 — Report Agent Internal Flow</h2>
  <p class="subtitle">Field visit report assistant. Detects language and intent, optionally enriches with product catalog context.</p>

  <div class="diagram-card">
    <h3>Report Agent Flow</h3>
    <div class="mermaid">
flowchart TD
    Q(["User question\nor raw notes"]):::input

    Q --> LANG["Language Detection\nFR · EN · Tunisian markers"]:::report
    LANG --> INTENT["Intent Detection\n7 intents (keyword-based)"]:::report

    INTENT --> MULTI{"Multiple\nintents?"}:::orch
    MULTI -->|yes| LOOP["Process each\nintent in order"]:::report
    MULTI -->|no| SINGLE["Single intent"]:::report

    LOOP & SINGLE --> RAG_CHECK{"Product\nmentioned?"}:::orch

    RAG_CHECK -->|yes, and intent is\ntechnical_help / Q&A / reformulate| FAISS["FAISS Catalog Search\nall-MiniLM-L6-v2\ntop-4 chunks"]:::backend
    RAG_CHECK -->|no| BUILD

    FAISS --> CTX["Format catalog context\ngamme · title · content"]:::backend
    CTX --> BUILD

    BUILD["Build prompt\n(intent-specific template)"]:::report
    BUILD --> LLM["LLM Call\ngpt-oss:20b-cloud\nJSON output enforced"]:::report

    LLM -->|"valid JSON"| PARSE["Parse answer\nfield from JSON"]:::report
    LLM -->|"parse fails"| FALLBACK["Keyword-based fallback\n(no LLM needed)"]:::report

    PARSE & FALLBACK --> FORMAT["Format to Markdown\n(intent → section heading)"]:::report
    FORMAT --> OUT(["Response panel\n'rapport (model)'"]):::output

    classDef input    fill:#1e2040,stroke:#6c63ff,color:#c4b5fd
    classDef orch     fill:#2d1f6e,stroke:#a78bfa,color:#ede9fe
    classDef report   fill:#2e2000,stroke:#fbbf24,color:#fef3c7
    classDef backend  fill:#0d1f3a,stroke:#60a5fa,color:#bfdbfe
    classDef output   fill:#0a2a1a,stroke:#34d399,color:#a7f3d0
    </div>
  </div>
</section>


<!-- ══════════════════════════════════════════════════════════
     SECTION 5 — PIPELINE 2 SCENARIOS
══════════════════════════════════════════════════════════ -->
<section id="scenarios-p2">
  <h2><span class="num">5</span>Pipeline 2 — Report Scenarios</h2>
  <p class="subtitle">All 7 intents the Report Agent handles. Multiple intents can be active in a single request.</p>

  <div class="diagram-card">
    <h3>Intent Routing</h3>
    <div class="mermaid">
flowchart LR
    IN(["User text"]):::input

    IN --> S["structure\n'donne-moi la structure\nd'un rapport'"]:::report
    IN --> E["example\n'donne-moi un exemple\nde rapport'"]:::report
    IN --> R["reformulate\n'reformule mes notes:\nvisite cardio omega3'"]:::report
    IN --> M["missing_points\n'qu'est-ce qui manque\ndans mon rapport?'"]:::report
    IN --> T["technical_help\n'que puis-je ajouter\ntechniquement?'"]:::report
    IN --> EV["evaluate\n'évalue mon rapport:\n[draft]'"]:::report
    IN --> QA["question_answer\n'quel est le dosage\nde l'Omega 3?'"]:::report

    S  --> OUT(["Markdown\nformatted\nresponse"]):::output
    E  --> OUT
    R  --> OUT
    M  --> OUT
    T  --> OUT
    EV --> OUT
    QA --> OUT

    classDef input  fill:#1e2040,stroke:#6c63ff,color:#c4b5fd
    classDef report fill:#2e2000,stroke:#fbbf24,color:#fef3c7
    classDef output fill:#0a2a1a,stroke:#34d399,color:#a7f3d0
    </div>
  </div>

  <div class="grid-2">

    <div class="scenario">
      <h4 style="color:var(--report)">📝 Reformulate Notes</h4>
      <p style="font-size:13px;color:var(--muted);margin-bottom:10px">
        "reformule mes notes : visite cardiologue, omega 3, intéressé"
      </p>
      <ul>
        <li>Detects raw note format (≤20 words + markers)</li>
        <li>Checks for product keywords → FAISS search</li>
        <li>LLM rewrites as professional visit report</li>
        <li>Fallback: regex-based reformulation</li>
      </ul>
      <span class="tag">reformulate</span>
      <span class="tag" style="color:var(--backend)">FAISS RAG</span>
    </div>

    <div class="scenario">
      <h4 style="color:var(--report)">🔍 Missing Points Check</h4>
      <p style="font-size:13px;color:var(--muted);margin-bottom:10px">
        "qu'est-ce qui manque dans mon rapport ?"
      </p>
      <ul>
        <li>10 structured sections checked</li>
        <li>Date · Client · Specialty · Location</li>
        <li>Objective · Products · Discussion</li>
        <li>Reaction · Outcome · Next actions</li>
        <li>Fallback: keyword scan, no LLM needed</li>
      </ul>
      <span class="tag">missing_points</span>
    </div>

    <div class="scenario">
      <h4 style="color:var(--report)">⭐ Report Evaluation</h4>
      <p style="font-size:13px;color:var(--muted);margin-bottom:10px">
        "évalue mon rapport : [draft text]"
      </p>
      <ul>
        <li>LLM assesses completeness and quality</li>
        <li>Returns: overall assessment + strengths + improvements</li>
        <li>Fallback: scores missing section count (0–2 good, 3–5 ok, 6+ weak)</li>
      </ul>
      <span class="tag">evaluate</span>
    </div>

    <div class="scenario">
      <h4 style="color:var(--report)">💊 Product Q&A (RAG)</h4>
      <p style="font-size:13px;color:var(--muted);margin-bottom:10px">
        "quel est le dosage de l'Omega 3 ?"
      </p>
      <ul>
        <li>FAISS semantic search over 22 product PPTXs</li>
        <li>Embeds query with all-MiniLM-L6-v2 (384-dim)</li>
        <li>Top-4 chunks injected as catalog context</li>
        <li>LLM answers without inventing information</li>
      </ul>
      <span class="tag">question_answer</span>
      <span class="tag" style="color:var(--backend)">FAISS RAG</span>
    </div>

  </div>
</section>


<!-- ══════════════════════════════════════════════════════════
     SECTION 6 — TOOL REFERENCE
══════════════════════════════════════════════════════════ -->
<section id="tools">
  <h2><span class="num">6</span>DataAgent Tool Reference</h2>
  <p class="subtitle">All 8 tools available to the DataAgent and when to use each one.</p>

  <div class="diagram-card" style="padding:0;overflow:hidden">
    <table class="ref-table">
      <thead>
        <tr>
          <th>Tool</th>
          <th>When to use</th>
          <th>Key parameters</th>
          <th>Returns</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>search_schema</code></td>
          <td>Unknown which table to query — search by keyword in table/column names</td>
          <td><code>keyword</code></td>
          <td>Matching tables with column list</td>
        </tr>
        <tr>
          <td><code>get_table_columns</code></td>
          <td>Confirm exact column names and types before querying an unfamiliar table</td>
          <td><code>table</code></td>
          <td>Typed column list</td>
        </tr>
        <tr>
          <td><code>list_modules</code></td>
          <td>Explore which modules and tables exist at a high level</td>
          <td>—</td>
          <td>Module → table list</td>
        </tr>
        <tr>
          <td><code>list_tables</code></td>
          <td>List all tables, optionally filtered to one module</td>
          <td><code>module?</code></td>
          <td>Table name list</td>
        </tr>
        <tr>
          <td><code>aggregate_table</code> ⭐</td>
          <td>KPIs · totals · rankings · period breakdowns · any GROUP BY summary</td>
          <td><code>groupBy</code> or <code>groupByExpressions</code> · <code>metrics</code> · <code>filters</code> · <code>having</code> · <code>sorts</code> · <code>distinct</code></td>
          <td>Aggregated rows with metric columns</td>
        </tr>
        <tr>
          <td><code>compare_periods</code> ⭐</td>
          <td>Year-over-year or any A vs B comparison — <strong>requires a dimension</strong> in groupBy</td>
          <td><code>period_a</code> · <code>period_b</code> · <code>groupBy</code> (mandatory) · <code>metrics</code> · <code>date_column</code></td>
          <td>Merged rows: metric_A · metric_B · growth_pct</td>
        </tr>
        <tr>
          <td><code>query_table</code></td>
          <td>Raw row listings · filtered searches · individual records · pending items</td>
          <td><code>filters</code> · <code>sort</code> · <code>page</code> · <code>size</code></td>
          <td>Paginated raw rows</td>
        </tr>
        <tr>
          <td><code>browse_table</code></td>
          <td>Preview table content without filters — explore sample values</td>
          <td><code>page</code> · <code>size</code></td>
          <td>First N rows, no filter</td>
        </tr>
      </tbody>
    </table>
  </div>
</section>


<!-- ══════════════════════════════════════════════════════════
     SECTION 7 — AGGREGATE API CHEATSHEET
══════════════════════════════════════════════════════════ -->
<section id="aggregate">
  <h2><span class="num">7</span>Aggregate API — Capabilities Cheat-Sheet</h2>
  <p class="subtitle">Everything the backend aggregate endpoint supports.</p>

  <div class="grid-2">

    <div class="diagram-card" style="margin-bottom:0">
      <h3>groupByExpressions — Date Functions</h3>
      <div class="mermaid">
flowchart LR
    COL["date column"]:::backend
    COL --> YEAR["YEAR(date)\n→ annee: 2024"]:::data
    COL --> MONTH["MONTH(date)\n→ mois: 3"]:::data
    COL --> QUARTER["QUARTER(date)\n→ trim: 1"]:::data
    COL --> WEEK["WEEK(date)\n→ semaine: 12"]:::data
    COL --> DAY["DAY(date)\n→ jour: 15"]:::data
    COL --> DATE["DATE(date)\n→ date: 2024-03-15"]:::data

    classDef backend fill:#0d1f3a,stroke:#60a5fa,color:#bfdbfe
    classDef data    fill:#3d1515,stroke:#f87171,color:#fecaca
      </div>
    </div>

    <div class="diagram-card" style="margin-bottom:0">
      <h3>Aggregate Power Features</h3>
      <div class="mermaid">
flowchart TD
    AGG["aggregate_table"]:::data
    AGG --> GB["groupBy\nplain columns"]:::orch
    AGG --> GBE["groupByExpressions\ndate functions"]:::orch
    AGG --> MET["metrics\nSUM · COUNT · AVG · MIN · MAX\n+ distinct: true"]:::orch
    AGG --> FLT["filters WHERE\n16 operators\nbetween · in · contains…"]:::backend
    AGG --> HAV["having HAVING\npost-aggregation filter\non metric aliases"]:::analysis
    AGG --> SRT["sorts multi-column\n[{col, asc/desc}, …]"]:::report

    classDef orch     fill:#2d1f6e,stroke:#a78bfa,color:#ede9fe
    classDef data     fill:#3d1515,stroke:#f87171,color:#fecaca
    classDef analysis fill:#0f2e22,stroke:#34d399,color:#a7f3d0
    classDef report   fill:#2e2000,stroke:#fbbf24,color:#fef3c7
    classDef backend  fill:#0d1f3a,stroke:#60a5fa,color:#bfdbfe
      </div>
    </div>

  </div>

  <div class="diagram-card" style="margin-top:16px;padding:0;overflow:hidden">
    <table class="ref-table">
      <thead>
        <tr>
          <th>Operator</th><th>SQL</th><th>Value</th>
          <th>Operator</th><th>SQL</th><th>Value</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>eq</code> / <code>neq</code></td><td>= / !=</td><td>string · number</td>
          <td><code>between</code></td><td>BETWEEN ? AND ?</td><td>[min, max] array</td>
        </tr>
        <tr>
          <td><code>gt</code> / <code>gte</code></td><td>&gt; / &gt;=</td><td>number · date</td>
          <td><code>in</code> / <code>notIn</code></td><td>IN / NOT IN</td><td>JSON array</td>
        </tr>
        <tr>
          <td><code>lt</code> / <code>lte</code></td><td>&lt; / &lt;=</td><td>number · date</td>
          <td><code>isNull</code> / <code>isNotNull</code></td><td>IS NULL</td><td>no value</td>
        </tr>
        <tr>
          <td><code>like</code> / <code>notLike</code></td><td>LIKE (use %)</td><td>string</td>
          <td><code>startsWith</code> / <code>endsWith</code></td><td>LIKE x% / %x</td><td>string (no %)</td>
        </tr>
        <tr>
          <td><code>contains</code></td><td>LIKE %x%</td><td>string (no %)</td>
          <td colspan="3" style="color:var(--muted);font-size:12px">All filters are AND-combined · max 500 rows/page</td>
        </tr>
      </tbody>
    </table>
  </div>

</section>

</div><!-- /page -->

<script>
mermaid.initialize({
  startOnLoad: true,
  theme: 'dark',
  themeVariables: {
    darkMode: true,
    background:     '#1a1d27',
    primaryColor:   '#2d1f6e',
    primaryTextColor: '#ede9fe',
    primaryBorderColor: '#a78bfa',
    lineColor:      '#6b7280',
    secondaryColor: '#0d1f3a',
    tertiaryColor:  '#0f2e22',
    nodeTextColor:  '#e2e8f0',
    edgeLabelBackground: '#1a1d27',
    clusterBkg:     '#1a1d27',
  },
  flowchart: { curve: 'basis', padding: 20 },
});

// Highlight active nav item on scroll
const sections = document.querySelectorAll('section[id]');
const navLinks  = document.querySelectorAll('nav a');

const observer = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      navLinks.forEach(a => a.classList.remove('active'));
      const link = document.querySelector(`nav a[href="#${e.target.id}"]`);
      if (link) link.classList.add('active');
    }
  });
}, { rootMargin: '-30% 0px -60% 0px' });

sections.forEach(s => observer.observe(s));
</script>
</body>
</html>
"""


def main() -> None:
    out = Path(__file__).parent / "pipeline_diagram.html"
    out.write_text(HTML, encoding="utf-8")
    print(f"Diagram written → {out}")
    webbrowser.open(out.as_uri())
    print("Opened in browser.")


if __name__ == "__main__":
    main()
