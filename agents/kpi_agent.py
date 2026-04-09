"""
KPI Agent — PLACEHOLDER

Receives raw rows from the DataAgent and the KPI spec from the Orchestrator.
Computes: totals, averages, rankings, growth rates, target vs actual comparisons.

NOT YET IMPLEMENTED — passes data through unchanged.
"""
from __future__ import annotations
from agents.data_agent import DataResult


class KpiAgent:
    def process(self, data_result: DataResult, kpi_spec: str = "") -> DataResult:
        # Store kpi_spec for future implementation
        data_result.kpi_spec = kpi_spec
        return data_result
