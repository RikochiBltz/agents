"""
Orchestrator Agent

Receives the raw user question and produces a full routing decision:
  1. Which pipeline to use (1, 2, or 3)
  2. data_query   — precise instruction for the DataAgent (what rows to fetch)
  3. kpi_spec     — what the KPI Agent must compute (Pipeline 1 only)
  4. analysis_spec — what the Analysis Agent must do (Pipeline 1 and 2)

Pipelines:
  1 → DataAgent → KPI Agent → Analysis Agent → Response
  2 → DataAgent → Analysis Agent → Response
  3 → Report Agent → Response
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from openai import OpenAI

import config

# ── Routing tool ──────────────────────────────────────────────────────
_ROUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "route_pipeline",
        "description": (
            "Route the user question to the correct pipeline and produce "
            "precise instructions for each downstream agent. "
            "If the question is out of scope, reject it immediately."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "rejected": {
                    "type": "boolean",
                    "description": (
                        "Set to true if the question is outside the allowed scope. "
                        "When true, only rejection_message is required — all other fields are ignored."
                    ),
                },
                "rejection_message": {
                    "type": "string",
                    "description": (
                        "Required when rejected=true. "
                        "A short, polite message explaining that the question is outside "
                        "the scope of the MediNote CRM system and what kinds of questions "
                        "ARE accepted. Keep the original language of the user."
                    ),
                },
                "pipeline": {
                    "type": "integer",
                    "enum": [1, 2, 3],
                    "description": (
                        "1 = KPI + Analysis: user wants computed metrics, rankings, totals, "
                        "growth rates, best/worst performers. KPI Agent does the math. "
                        "2 = Data + Analysis: user wants raw rows, listings, filtered search, "
                        "trend exploration. No KPI computation needed. "
                        "3 = Report: user wants a narrative report or executive summary."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": "One sentence explaining the pipeline choice.",
                },
                "data_query": {
                    "type": "string",
                    "description": (
                        "A clarified version of the user's question for the DataAgent. "
                        "Resolve ambiguities (e.g. relative dates → absolute year/period), "
                        "but do NOT specify tables, columns, filters, or SQL syntax — "
                        "the DataAgent handles all of that itself. "
                        "Keep the original language."
                    ),
                },
                "kpi_spec": {
                    "type": "string",
                    "description": (
                        "Pipeline 1 only. Exact KPI calculations the KPI Agent must perform "
                        "on the data returned by DataAgent. Be explicit: "
                        "'Compute total TTC, total quantity, average TTC per transaction, "
                        "and rank by total TTC descending.' "
                        "Leave empty for Pipeline 2 and 3."
                    ),
                },
                "analysis_spec": {
                    "type": "string",
                    "description": (
                        "What the Analysis Agent must do after receiving data (or KPI results). "
                        "Examples: 'Identify top and bottom performers', "
                        "'Detect anomalies in monthly trend', 'Compare zones'. "
                        "Leave empty for Pipeline 3."
                    ),
                },
            },
            "required": ["rejected"],
        },
    },
}

_SYSTEM_PROMPT = """You are the Orchestrator for the MediNote CRM AI system — a pharmaceutical sales CRM.

Your first job is to decide whether the question is within scope.
Your second job is to route in-scope questions to the right pipeline.

## SCOPE GUARDRAIL — CHECK FIRST

ALLOWED: Any question that can be answered by querying the company's database —
regardless of what the data contains (sales, vehicles, products, clients, stock,
payments, visits, or any other entity stored in the system).
When in doubt, allow it.

REJECTED: Questions that have nothing to do with querying or analysing data, for example:
  • General knowledge (history, geography, science, politics)
  • Personal advice, creative writing, jokes, poetry
  • Programming help unrelated to this system
  • Anything that cannot be answered from a database

If the question is out of scope → call route_pipeline(rejected=true, rejection_message="...")
If the question is in scope → call route_pipeline(rejected=false, pipeline=..., ...)

## PIPELINE SELECTION

Pipeline 1 — DataAgent → KPI Agent → Analysis Agent
  Use when: user wants computed KPIs — totals, averages, rankings, growth rates,
  best/worst performers, target vs actual comparisons.
  DataAgent fetches data at an intermediate breakdown level — NOT the final KPI value.
  The KPI Agent receives that breakdown and does the final computation.
  The data_query must ask for the right dimension/granularity, not the final answer.
  Examples:
    "Chiffre d'affaires de 2024"
      → data_query: "Récupère le CA mensuel de l'année 2024."
      → kpi_spec: "Calcule le total CA = SUM de tous les mois de 2024."
    "Top 5 délégués par CA 2023"
      → data_query: "Récupère le CA par délégué pour l'année 2023."
      → kpi_spec: "Classe les délégués par CA décroissant, retourne le top 5."
    "Croissance des ventes 2022 vs 2023"
      → data_query: "Récupère le CA mensuel pour 2022 et 2023."
      → kpi_spec: "Calcule le CA total de chaque année et le taux de croissance."

Pipeline 2 — DataAgent → Analysis Agent
  Use when: user wants raw data, listings, filtered searches, stock levels, pending items.
  DataAgent fetches the rows. Analysis Agent interprets them.
  Examples:
    "Liste des demandes en attente"
    "Sessions d'animation de janvier à juin"
    "Clients avec solde > 5000"

Pipeline 3 — Report Agent
  Use when: user explicitly asks for a written report, summary, or document.
  Examples: "Écris un rapport sur les ventes Q1 2024"

## DATA QUERY RULES
- Write a clarified, natural-language question for the DataAgent.
- Resolve relative dates to absolute periods (today = 2026-04-05).
- Do NOT mention tables, columns, filters, SQL, or row counts — the DataAgent decides all of that.
- For Pipeline 1: ask for data at the dimension level needed for the KPI, not the final answer.
  The DataAgent must return a breakdown (by month, by delegate, by product…) so the KPI Agent
  has real computation to perform. Never ask "what is the total" in the data_query for Pipeline 1.
- Keep the original language.

## KPI SPEC RULES
- Be explicit about every metric: name, formula, and grouping dimension
- Example: "1. Total TTC = SUM(ttc) for all rows. 2. Rank delegates by total TTC descending."
- Include the time period for context

## CLARIFICATION RULES
- Convert relative dates to absolute ranges (today = 2026-04-05)
- Keep the original language (French stays French)
- Do NOT invent details not in the original question

Always call route_pipeline(). Never respond with plain text.
"""


@dataclass
class RoutingDecision:
    pipeline: int
    reasoning: str
    data_query: str                    # instruction for DataAgent
    kpi_spec: str = ""                 # instruction for KPI Agent (Pipeline 1)
    analysis_spec: str = ""            # instruction for Analysis Agent (Pipeline 1 & 2)
    raw_question: str = ""
    rejected: bool = False
    rejection_message: str = ""


class Orchestrator:
    def __init__(self):
        self._llm = OpenAI(
            base_url=config.ORCHESTRATOR_BASE_URL,
            api_key=config.ORCHESTRATOR_API_KEY,
        )

    def route(self, question: str) -> RoutingDecision:
        response = self._llm.chat.completions.create(
            model=config.ORCHESTRATOR_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": question},
            ],
            tools=[_ROUTE_TOOL],
            tool_choice={"type": "function", "function": {"name": "route_pipeline"}},
        )

        tc = response.choices[0].message.tool_calls[0]
        args = json.loads(tc.function.arguments)

        if args.get("rejected"):
            return RoutingDecision(
                pipeline=0,
                reasoning="",
                data_query="",
                rejected=True,
                rejection_message=args.get("rejection_message", "Question hors périmètre."),
                raw_question=question,
            )

        return RoutingDecision(
            pipeline=args["pipeline"],
            reasoning=args.get("reasoning", ""),
            data_query=args["data_query"],
            kpi_spec=args.get("kpi_spec", ""),
            analysis_spec=args.get("analysis_spec", ""),
            raw_question=question,
        )
