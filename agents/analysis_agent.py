"""
Analysis Agent

Receives the data returned by DataAgent (or KPI Agent) and produces
a clear explanation of what the data shows, following the analysis_spec
from the Orchestrator.
"""
from __future__ import annotations

import json

from openai import OpenAI

import config
from agents.data_agent import DataResult

_MAX_ROWS_IN_PROMPT = 100   # truncate to avoid overloading the context


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

        total_rows = data_result.data.get("totalRows", 0)
        if total_rows == 0:
            data_result.analysis = ""
            return data_result

        data_result.analysis = self._explain(
            data=data_result.data,
            analysis_spec=analysis_spec,
            question=question,
        )
        return data_result

    def _explain(self, data: dict, analysis_spec: str, question: str) -> str:
        rows = data.get("content", data.get("rows", []))
        total_rows = data.get("totalRows", len(rows))

        # Truncate to keep prompt size reasonable
        truncated = rows[:_MAX_ROWS_IN_PROMPT]
        data_snippet = {
            "totalRows": total_rows,
            "showing": len(truncated),
            "rows": truncated,
        }

        system = (
            "You are MediNote Analysis Agent. "
            "You receive raw data from a CRM database and explain what it shows. "
            "Be concise, structured, and stay in the same language as the user's question. "
            "Do not repeat the raw data — summarize and interpret it. "
            "Use bullet points or short paragraphs."
        )

        user_parts = []
        if question:
            user_parts.append(f"**User question:** {question}")
        if analysis_spec:
            user_parts.append(f"**What to analyze:** {analysis_spec}")
        user_parts.append(
            f"**Data ({total_rows} rows"
            + (f", showing first {len(truncated)}" if len(truncated) < total_rows else "")
            + "):**\n```json\n"
            + json.dumps(data_snippet, indent=2, ensure_ascii=False, default=str)
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
