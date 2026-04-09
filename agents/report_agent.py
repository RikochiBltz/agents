"""
Report Agent — PLACEHOLDER

Receives a topic/question and produces a formatted narrative report.
Does NOT call the backend directly — receives data from DataAgent.

NOT YET IMPLEMENTED.
"""
from __future__ import annotations
from agents.data_agent import DataResult


class ReportAgent:
    def process(self, question: str) -> DataResult:
        # Placeholder
        result = DataResult(clarified_question=question)
        result.error = "Report Agent is not yet implemented."
        return result
