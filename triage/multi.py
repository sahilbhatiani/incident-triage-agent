"""Approach B: Logs / Metrics / Knowledge specialists in parallel, reconciled by a coordinator."""

from __future__ import annotations

import json
import operator
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from triage.loop import build_loop, run_loop
from triage.prompts import COORDINATOR, SPECIALISTS
from triage.schemas import Diagnosis, Finding, FindingsSubmission, FollowupRequest, coerce_diagnosis, coerce_findings
from triage.single import submit_diagnosis_tool

TOTAL_BUDGET = 15  # same as the single agent
SPECIALIST_BUDGET = 4  # x3 specialists = 12
FOLLOWUP_BUDGET = 3  # 12 + 3 = 15
MAX_FINDINGS = 5
MAX_FOLLOWUPS = 1

SPECIALIST_TOOLS = {
    "logs": ["query_logs", "get_topology"],
    "metrics": ["get_metric", "list_anomalies"],
    "knowledge": ["search_kb"],
}


class MultiState(TypedDict):
    alert: dict
    findings: Annotated[list, operator.add]
    followups: int
    followup_request: dict | None
    diagnosis: dict | None


def _submit_findings_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda **kw: "submitted", name="submit_findings", args_schema=FindingsSubmission,
        description="Hand off at most 5 evidence findings to the coordinator. Ends your investigation.")


def _followup_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda **kw: "requested", name="request_followup", args_schema=FollowupRequest,
        description="Ask one specialist one targeted question. Allowed once per incident.")


def _render_findings(findings: list[dict]) -> str:
    return "\n".join(
        f"- [{f['agent']}] (confidence {f['confidence']:.2f}) {f['claim']} "
        f"cites: {', '.join(c['ref'] for c in f['citations']) or 'none'}" for f in findings)


class MultiAgent:
    def __init__(self, llm, tools, tracer=None):
        self.llm = llm
        self.tracer = tracer
        self.specialist_tools = {r: tools.as_langchain(names, r) for r, names in SPECIALIST_TOOLS.items()}
        self.coordinator_tools = [submit_diagnosis_tool(), _followup_tool()]
        submit = _submit_findings_tool()
        self.loops = {
            (r, b): build_loop(llm, self.specialist_tools[r], submit, b, r, tracer)
            for r in SPECIALIST_TOOLS for b in (SPECIALIST_BUDGET, FOLLOWUP_BUDGET)
        }
        self.graph = self._build()

    # --- nodes ----------------------------------------------------------------------------

    def _specialist(self, payload: dict):
        role, question = payload["role"], payload.get("question")
        budget = FOLLOWUP_BUDGET if question else SPECIALIST_BUDGET
        if self.tracer:
            self.tracer.emit(role, "start", followup=bool(question))
        user = "Alert:\n" + json.dumps(payload["alert"], indent=2)
        if question:
            user += f"\n\nFollow-up question from the coordinator: {question}"
        system = SPECIALISTS[role].replace("{budget}", str(budget))
        res = run_loop(self.loops[(role, budget)], system, user)
        findings = coerce_findings(res["submitted"], role, MAX_FINDINGS)
        if self.tracer:
            for f in findings:
                self.tracer.emit(role, "finding", **f.model_dump(exclude={"agent"}))
            self.tracer.handoff(role, [c.ref for f in findings for c in f.citations])
            self.tracer.emit(role, "end", tool_calls=res["calls"], findings=len(findings))
        return {"findings": [f.model_dump() for f in findings]}

    def _coordinator(self, state: MultiState):
        can_follow = state["followups"] < MAX_FOLLOWUPS
        tools = self.coordinator_tools if can_follow else self.coordinator_tools[:1]
        bound = self.llm.bind_tools(tools, tool_choice="any" if can_follow else "submit_diagnosis")
        messages = [SystemMessage(content=COORDINATOR),
                    HumanMessage(content="Alert:\n" + json.dumps(state["alert"], indent=2)
                                 + "\n\nSpecialist findings:\n" + _render_findings(state["findings"]))]
        for _ in range(2):
            msg = bound.invoke(messages)
            if self.tracer:
                self.tracer.llm("coordinator", getattr(msg, "usage_metadata", None))
            for tc in msg.tool_calls:
                if tc["name"] == "request_followup" and can_follow:
                    req = FollowupRequest.model_validate(tc["args"]).model_dump()
                    if self.tracer:
                        self.tracer.emit("coordinator", "followup", **req)
                    return {"followup_request": req, "followups": state["followups"] + 1}
                if tc["name"] == "submit_diagnosis":
                    return {"diagnosis": self._ground(tc["args"], state["findings"]), "followup_request": None}
            bound = self.llm.bind_tools(tools[:1], tool_choice="submit_diagnosis")
        return {"diagnosis": None, "followup_request": None}

    def _ground(self, args: dict, findings: list[dict]) -> dict:
        """Keep only citations that a specialist actually handed off."""
        allowed = {c["ref"] for f in findings for c in f["citations"]}
        d = coerce_diagnosis(args)
        kept = [c for c in d.citations if c.ref in allowed]
        if self.tracer and len(kept) < len(d.citations):
            self.tracer.emit("coordinator", "dropped_citations", refs=[c.ref for c in d.citations if c.ref not in allowed])
        return d.model_copy(update={"citations": kept}).model_dump()

    def _route_start(self, state: MultiState):
        return [Send("specialist", {"role": r, "alert": state["alert"]}) for r in SPECIALIST_TOOLS]

    def _route_coordinator(self, state: MultiState):
        req = state.get("followup_request")
        if req and state.get("diagnosis") is None:
            return [Send("specialist", {"role": req["specialist"], "alert": state["alert"], "question": req["question"]})]
        return END

    def _build(self):
        g = StateGraph(MultiState)
        g.add_node("specialist", self._specialist)
        g.add_node("coordinator", self._coordinator)
        g.add_conditional_edges(START, self._route_start, ["specialist"])
        g.add_edge("specialist", "coordinator")
        g.add_conditional_edges("coordinator", self._route_coordinator, ["specialist", END])
        return g.compile()

    def triage(self, alert: dict) -> Diagnosis:
        state = self.graph.invoke({"alert": alert, "findings": [], "followups": 0, "followup_request": None,
                                   "diagnosis": None}, {"recursion_limit": 50})
        self.last_state = state
        diagnosis = coerce_diagnosis(state["diagnosis"])
        if self.tracer:
            self.tracer.emit("coordinator", "diagnosis", **diagnosis.model_dump())
        return diagnosis


def build_multi_agent(llm, tools, tracer=None) -> MultiAgent:
    """Return the agent: router -> Send x3 -> coordinator (-> 1 follow-up) -> Diagnosis."""
    return MultiAgent(llm, tools, tracer)
