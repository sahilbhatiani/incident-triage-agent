"""Approach A: one ReAct agent with every tool."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool

from triage.loop import build_loop, run_loop
from triage.prompts import SINGLE
from triage.schemas import Diagnosis, coerce_diagnosis
from triage.tools import ALL_TOOLS

TOOL_BUDGET = 15


def submit_diagnosis_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda **kw: "submitted", name="submit_diagnosis", args_schema=Diagnosis,
        description="Submit the final root-cause diagnosis. Ends the investigation.")


class SingleAgent:
    def __init__(self, llm, tools, tracer=None, budget: int = TOOL_BUDGET):
        self.tools = tools.as_langchain(ALL_TOOLS, "single")
        self.tool_names = [t.name for t in self.tools]
        self.budget = budget
        self.tracer = tracer
        self.graph = build_loop(llm, self.tools, submit_diagnosis_tool(), budget, "single", tracer)

    def triage(self, alert: dict) -> Diagnosis:
        system = SINGLE.replace("{budget}", str(self.budget))
        res = run_loop(self.graph, system, "Alert:\n" + json.dumps(alert, indent=2))
        diagnosis = coerce_diagnosis(res["submitted"])
        if self.tracer:
            self.tracer.emit("single", "diagnosis", **diagnosis.model_dump())
        return diagnosis


def build_single_agent(llm, tools, tracer=None) -> SingleAgent:
    """Return the agent; `.triage(alert)` ends with a validated Diagnosis."""
    return SingleAgent(llm, tools, tracer)
