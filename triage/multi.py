"""Approach B: Logs / Metrics / Knowledge specialists in parallel, reconciled by a coordinator."""

from __future__ import annotations

SPECIALIST_BUDGET = 6
MAX_FINDINGS = 5
MAX_FOLLOWUPS = 1


def build_multi_agent(llm, tools):
    """Return a compiled LangGraph: router -> Send x3 -> coordinator -> Diagnosis."""
    raise NotImplementedError
