"""Scripted responders for ScriptedChatModel used by the agent scenarios."""

import json
import re

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from tests.conftest import tool_call

GOOD = {"fault": "db_pool_saturation", "service": "postgres", "explanation": "pool exhausted first",
        "citations": [{"kind": "metric", "ref": "postgres.db_pool_used@1200-1500"}], "confidence": 0.8,
        "operator_checks": ["check pool"], "safe_next_steps": ["page DBA"]}


def n_ai(messages):
    return sum(isinstance(m, AIMessage) for m in messages)


def role_of(messages):
    sys = next((m.content for m in messages if isinstance(m, SystemMessage)), "")
    for role, marker in (("logs", "Logs specialist"), ("metrics", "Metrics specialist"),
                         ("knowledge", "Knowledge specialist"), ("coordinator", "incident commander")):
        if marker in sys:
            return role
    return "single"


def seen_log_ids(messages):
    return [i for m in messages if isinstance(m, ToolMessage) for i in re.findall(r"L\d{6}", m.content)]


def sequence(*steps):
    """Return the i-th scripted message where i = AI turns so far in this conversation."""
    def responder(messages, bound):
        i = n_ai(messages)
        step = steps[min(i, len(steps) - 1)]
        return step(messages) if callable(step) else step
    return responder


def forever(name="list_anomalies", args=None):
    return lambda messages, bound: tool_call(name, args or {})


def specialist_default(messages, bound):
    role, i = role_of(messages), n_ai(messages)
    first = {"logs": ("query_logs", {"service": "postgres", "level": "ERROR", "limit": 5}),
             "metrics": ("list_anomalies", {}),
             "knowledge": ("search_kb", {"query": "timeout acquiring connection"})}[role]
    if i == 0:
        return tool_call(*first)
    ids = seen_log_ids(messages)
    cites = [{"kind": "log", "ref": ids[0]}] if ids else [{"kind": "metric", "ref": "postgres.db_pool_used@1200-1500"}]
    findings = [{"claim": f"{role} finding {k}", "citations": cites, "confidence": 0.7} for k in range(7)]
    return tool_call("submit_findings", {"findings": findings})
