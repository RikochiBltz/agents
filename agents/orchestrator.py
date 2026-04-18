"""
Orchestrator Agent

Receives the raw user question and produces a full routing decision:
  1. Which pipeline to use (1 or 2)
  2. data_query    — precise instruction for the DataAgent (Pipeline 1)
  3. analysis_spec — what the Analysis Agent must do (Pipeline 1)

Pipelines:
  1 → DataAgent → Analysis Agent → Response
  2 → Report Agent → Response
  3 → Doctor Agent → Response
"""
from __future__ import annotations

import json
from dataclasses import dataclass

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
                        "When true, only rejection_message is required."
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
                        "1 = DataAgent + Analysis: user wants any data query, KPI, "
                        "ranking, total, trend, comparison, or analysis of company data. "
                        "2 = Report Agent: user wants help with field visit reports — "
                        "reformulating notes, checking structure, identifying missing points, "
                        "evaluating a draft, getting a report example, asking product questions "
                        "(dosage, indication, composition), or any visit-report writing assistance. "
                        "3 = Doctor Agent: user wants profile information about a specific doctor "
                        "(name, specialty, city, CROM, order number) OR wants to know which products "
                        "to recommend for a doctor's specialty. Use this when the question is about "
                        "WHO a doctor is, not about CRM data (sales, visits, balances) for that doctor."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": "One sentence explaining the pipeline choice.",
                },
                "data_query": {
                    "type": "string",
                    "description": (
                        "Pipeline 1 only. A clarified version of the user's question for the DataAgent. "
                        "Resolve ambiguities (e.g. relative dates → absolute year/period), "
                        "but do NOT specify tables, columns, filters, or SQL syntax — "
                        "the DataAgent handles all of that itself. "
                        "Keep the original language."
                    ),
                },
                "analysis_spec": {
                    "type": "string",
                    "description": (
                        "Pipeline 1 only. What the Analysis Agent must do after receiving data. "
                        "Examples: 'Identify top and bottom performers by CA', "
                        "'Detect anomalies in monthly trend', 'Compute growth rate 2023→2024', "
                        "'Compare zones and highlight best performers'. "
                        "Leave empty for Pipeline 2."
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
regardless of what the data contains (sales, products, clients, stock,
payments, visits, delegates, zones, or any other entity stored in the system).
When in doubt, allow it.

REJECTED: Questions that have nothing to do with querying or analysing data, for example:
  • General knowledge (history, geography, science, politics)
  • Personal advice, creative writing, jokes, poetry
  • Programming help unrelated to this system
  • Anything that cannot be answered from a database

If the question is out of scope → call route_pipeline(rejected=true, rejection_message="...")
If the question is in scope → call route_pipeline(rejected=false, pipeline=..., ...)

## PIPELINE SELECTION

Pipeline 1 — DataAgent → Analysis Agent
  Use for ALL data questions:
  • KPIs and metrics: totals, averages, sums, counts
  • Rankings and top-N: best delegates, top products, highest zones
  • Period comparisons: year-over-year, month-over-month, growth rates
  • Trends and breakdowns: monthly evolution, by-zone distribution
  • Raw listings and searches: pending demands, client balances, stock levels
  The DataAgent fetches and computes the data. The Analysis Agent interprets it.

  Examples:
    "Chiffre d'affaires de 2024"
      → data_query: "Récupère le CA total pour l'année 2024."
      → analysis_spec: "Donne le total CA 2024 et compare avec le contexte général."
    "Top 5 délégués par CA 2023"
      → data_query: "Récupère le CA par délégué pour l'année 2023, top 5 décroissant."
      → analysis_spec: "Identifie les 5 meilleurs délégués et commente leur performance."
    "Croissance des ventes 2022 vs 2023"
      → data_query: "Compare le CA total de 2022 et 2023 par délégué."
      → analysis_spec: "Calcule et commente le taux de croissance 2022→2023."

Pipeline 2 — Report Agent
  Use when the user wants field visit report assistance:
  • Reformulate raw notes into a professional report
  • Check or show the structure of a visit report
  • Identify missing sections in a draft report
  • Evaluate whether a report is complete
  • Get an example of a well-written visit report
  • Ask product-specific questions (dosage, indication, composition, side effects)
  • Get technical/scientific suggestions to enrich a report

  Examples:
    "reformule mes notes : visite cardiologue, omega 3, intéressé"
      → pipeline 2
    "qu'est-ce qui manque dans mon rapport ?"
      → pipeline 2
    "donne-moi la structure d'un rapport de visite"
      → pipeline 2
    "quel est le dosage de l'Omega 3 ?"
      → pipeline 2
    "évalue mon rapport : [draft text]"
      → pipeline 2

Pipeline 3 — Doctor Agent
  Use when the user asks about a specific doctor's identity or profile:
  • Who is a specific doctor (name, specialty, city, CROM, order number)
  • What products to recommend for a doctor's specialty
  • Doctor contact or registration details

  Key distinction:
    "info sur Dr. X"           → pipeline 3  (profile lookup)
    "CA des visites chez Dr. X" → pipeline 1  (CRM data query)
    "visite chez Dr. X, notes" → pipeline 2  (report writing)

  Examples:
    "give me information about doctor syrine azza mannoubi"  → pipeline 3
    "qui est Dr. Ben Ali cardiologue Tunis"                  → pipeline 3
    "quels produits recommander à un cardiologue ?"          → pipeline 3
    "info sur le médecin Slim Pneumologue Sfax"              → pipeline 3

## DATA QUERY RULES
- Write a clarified, natural-language question for the DataAgent.
- Resolve relative dates to absolute periods (today = 2026-04-09).
- Do NOT mention tables, columns, filters, SQL, or row counts — the DataAgent decides all of that.
- Keep the original language.

## CLARIFICATION RULES
- Convert relative dates to absolute ranges (today = 2026-04-09)
- Keep the original language (French stays French)
- Do NOT invent details not in the original question

Always call route_pipeline(). Never respond with plain text.
"""


@dataclass
class RoutingDecision:
    pipeline: int
    reasoning: str
    data_query: str                    # instruction for DataAgent (Pipeline 1)
    analysis_spec: str = ""            # instruction for Analysis Agent (Pipeline 1)
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
            data_query=args.get("data_query", ""),
            analysis_spec=args.get("analysis_spec", ""),
            raw_question=question,
        )
