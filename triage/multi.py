"""Approach B: Logs / Metrics / Knowledge specialists in parallel, reconciled by a coordinator."""

from __future__ import annotations

TOTAL_BUDGET = 15  # same as the single agent
SPECIALIST_BUDGET = 4  # x3 specialists = 12
FOLLOWUP_BUDGET = 3  # 12 + 3 = 15
MAX_FINDINGS = 5
MAX_FOLLOWUPS = 1


def build_multi_agent(llm, tools):
    """Return a compiled LangGraph: router -> Send x3 -> coordinator -> Diagnosis."""
    raise NotImplementedError
