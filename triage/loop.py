"""Budgeted ReAct loop as a LangGraph subgraph, shared by the single agent and every specialist.

The loop ends when the model calls its submit tool. Once the tool budget is spent the model is
bound to the submit tool only; if it still refuses, the loop ends with nothing submitted.
"""

from __future__ import annotations

import json
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

MAX_RESULT_CHARS = 6000
MAX_STRAYS = 2  # model turns allowed after the budget without submitting


class LoopState(TypedDict):
    messages: Annotated[list, add_messages]
    calls: int
    strays: int
    submitted: dict | None


def build_loop(llm, tools: list[StructuredTool], submit: StructuredTool, budget: int, agent: str, tracer=None):
    by_name = {t.name: t for t in tools}

    def agent_node(state: LoopState):
        exhausted = state["calls"] >= budget
        bound = llm.bind_tools([submit], tool_choice=submit.name) if exhausted else llm.bind_tools([*tools, submit])
        msg: AIMessage = bound.invoke(state["messages"])
        if tracer:
            tracer.llm(agent, getattr(msg, "usage_metadata", None))
        for tc in msg.tool_calls:
            if tc["name"] == submit.name:
                return {"messages": [msg], "submitted": tc["args"]}
        return {"messages": [msg], "strays": state["strays"] + (1 if exhausted or not (msg.tool_calls or msg.invalid_tool_calls) else 0)}

    def tools_node(state: LoopState):
        last: AIMessage = state["messages"][-1]
        out, calls = [], state["calls"]
        for tc in last.tool_calls:
            if calls >= budget or tc["name"] not in by_name:
                text = json.dumps({"error": "tool budget exhausted; call " + submit.name})
            else:
                calls += 1
                try:
                    text = json.dumps(by_name[tc["name"]].invoke(tc["args"]), default=str)
                except Exception as e:  # bad arguments are reported back to the model
                    text = json.dumps({"error": str(e)[:300]})
            out.append(ToolMessage(content=text[:MAX_RESULT_CHARS], tool_call_id=tc["id"]))
        # malformed calls (unparseable JSON args) still need a reply or the API rejects the next turn
        for bad in getattr(last, "invalid_tool_calls", []) or []:
            out.append(ToolMessage(content=json.dumps({"error": "invalid tool call arguments; retry"}),
                                   tool_call_id=bad["id"]))
        return {"messages": out, "calls": calls}

    def nudge_node(state: LoopState):
        return {"messages": [HumanMessage(content=f"Call {submit.name} now with your best answer.")]}

    def route(state: LoopState):
        if state["submitted"] is not None or state["strays"] > MAX_STRAYS:
            return END
        last = state["messages"][-1]
        return "tools" if last.tool_calls or getattr(last, "invalid_tool_calls", None) else "nudge"

    g = StateGraph(LoopState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_node("nudge", nudge_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, ["tools", "nudge", END])
    g.add_edge("tools", "agent")
    g.add_edge("nudge", "agent")
    return g.compile()


def run_loop(graph, system: str, user: str) -> dict[str, Any]:
    state = graph.invoke(
        {"messages": [SystemMessage(content=system), HumanMessage(content=user)], "calls": 0, "strays": 0, "submitted": None},
        {"recursion_limit": 100},
    )
    return {"submitted": state["submitted"], "calls": state["calls"]}
