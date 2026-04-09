"""
Analysis Agent

Receives the data returned by DataAgent and produces:
  1. A direct answer to the user's question
  2. Trend analysis — direction, patterns, top/bottom performers, anomalies
"""
from __future__ import annotations

import json

from openai import OpenAI

import config
from agents.data_agent import DataResult

_MAX_ROWS_IN_PROMPT = 100


class AnalysisAgent:
    def __init__(self):
        self._llm = OpenAI(
            base_url=config.ANALYSIS_BASE_URL,
            api_key=config.ANALYSIS_API_KEY,
        )

    def process(
        self,
        data_result: DataResult,
        analysis_spec: str = "",
        question: str = "",
    ) -> DataResult:
        data_result.analysis_spec = analysis_spec

        if data_result.data is None or data_result.error:
            data_result.analysis = ""
            return data_result

        if data_result.data.get("totalRows", 0) == 0:
            data_result.analysis = ""
            return data_result

        data_result.analysis = self._analyse(
            data=data_result.data,
            analysis_spec=analysis_spec,
            question=question,
        )
        return data_result

    def _analyse(self, data: dict, analysis_spec: str, question: str) -> str:
        rows       = data.get("content", data.get("rows", []))
        total_rows = data.get("totalRows", len(rows))
        columns    = data.get("columns", [])
        truncated  = rows[:_MAX_ROWS_IN_PROMPT]
        is_partial = len(truncated) < total_rows

        # Build a compact data block so the model has full context
        data_block = {
            "columns":   columns,
            "totalRows": total_rows,
            **({"showing": len(truncated), "note": "first rows only — totals may be partial"} if is_partial else {}),
            "rows": truncated,
        }

        system = """You are the MediNote Analysis Agent for a pharmaceutical sales CRM.
You receive aggregated or raw data returned by the DataAgent and must produce a sharp, useful analysis.

## YOUR JOB — always do both:

1. **Direct answer** — answer the user's question concisely using the actual numbers from the data.
   Lead with the key figure or finding. Do not make the user search for it.

2. **Trend & insight** — after the direct answer, identify:
   - Overall direction (growth, decline, stable, seasonal pattern)
   - Top and bottom performers (highest/lowest values, biggest change)
   - Notable gaps, anomalies, or concentrations worth highlighting
   - If it is a period comparison (growth_pct columns present): rank by growth, flag negatives

## RULES
- Stay in the same language as the user's question.
- Never repeat raw rows — work from the numbers, not the table.
- If data is partial (showing first N rows of a larger result), say so and caveat totals accordingly.
- Be concise: 3–6 bullet points or two short paragraphs. No filler text.
- Use exact numbers from the data — do not round unless formatting for readability."""

        user_parts = []
        if question:
            user_parts.append(f"**Question:** {question}")
        if analysis_spec:
            user_parts.append(f"**Analysis focus:** {analysis_spec}")
        user_parts.append(
            f"**Data ({total_rows} row{'s' if total_rows != 1 else ''}"
            + (f", showing first {len(truncated)}" if is_partial else "")
            + "):**\n```json\n"
            + json.dumps(data_block, indent=2, ensure_ascii=False, default=str)
            + "\n```"
        )

        try:
            response = self._llm.chat.completions.create(
                model=config.ANALYSIS_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": "\n\n".join(user_parts)},
                ],
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            return f"(Analysis failed: {e})"
