"""Step definitions for multi_agent.feature."""

from pytest_bdd import given, parsers, scenarios, then, when

from tests.conftest import ScriptedChatModel, tool_call
from tests.scripts import GOOD, n_ai, role_of, specialist_default
from triage.multi import build_multi_agent
from triage.run import make_llm, triage_incident
from triage.schemas import Diagnosis
from triage.tools import IncidentTools
from triage.tracing import Tracer

scenarios("multi_agent.feature")


def coordinator(always_followup=False, extra_citation=None):
    def respond(messages, bound):
        if always_followup:
            return tool_call("request_followup", {"specialist": "logs", "question": "which service logged first?"})
        cites = [{"kind": "metric", "ref": "postgres.db_pool_used@1200-1500"}]
        if extra_citation:
            cites.append({"kind": "log", "ref": extra_citation})
        return tool_call("submit_diagnosis", {**GOOD, "citations": cites})
    return respond


def make(spec_responder, coord):
    def responder(messages, bound):
        return coord(messages, bound) if role_of(messages) == "coordinator" else spec_responder(messages, bound)
    return responder


@given("a scripted fake LLM for each specialist and the coordinator")
def default_llm(ctx):
    ctx["llm"] = ScriptedChatModel(responder=make(specialist_default, coordinator(extra_citation="L999999")), delay=0.05)


@given("every specialist's fake LLM keeps requesting tool calls forever")
def forever(ctx):
    def spec(messages, bound):
        name = {"logs": "query_logs", "metrics": "list_anomalies", "knowledge": "search_kb"}[role_of(messages)]
        return tool_call(name, {"query": "x"} if name == "search_kb" else {})
    ctx["spec"] = spec
    ctx["llm"] = ScriptedChatModel(responder=make(spec, coordinator()))


@given("the specialists' findings conflict so a follow-up happens")
@given("the Logs and Metrics specialists blame different services")
def conflict(ctx):
    ctx["llm"] = ScriptedChatModel(responder=make(ctx.get("spec", specialist_default), coordinator(always_followup=True)))


@given("the real agent model")
def real_model(ctx):
    ctx["llm"] = make_llm()
    ctx["live"] = True


@when("I build the multi-agent graph")
def build(ctx, kb_retriever):
    ctx["agent"] = build_multi_agent(ctx["llm"], IncidentTools(ctx["incident_dir"], kb_retriever))


@when("the multi-agent graph triages the incident")
def run(ctx, kb_retriever):
    ctx["tracer"] = Tracer("multi-test")
    retriever = None if ctx.get("live") else kb_retriever
    ctx["out"] = triage_incident(ctx["incident_dir"], "multi", ctx["llm"], retriever, ctx["tracer"])
    ctx["events"] = ctx["tracer"].events


def _names(tools):
    return sorted(t.name for t in tools)


@then("the Logs specialist has query_logs and get_topology")
def logs_tools(ctx):
    assert _names(ctx["agent"].specialist_tools["logs"]) == ["get_topology", "query_logs"]


@then("the Metrics specialist has get_metric and list_anomalies")
def metrics_tools(ctx):
    assert _names(ctx["agent"].specialist_tools["metrics"]) == ["get_metric", "list_anomalies"]


@then("the Knowledge specialist has search_kb")
def kb_tools(ctx):
    assert _names(ctx["agent"].specialist_tools["knowledge"]) == ["search_kb"]


@then("the coordinator has no data tools")
def coord_tools(ctx):
    assert _names(ctx["agent"].coordinator_tools) == ["request_followup", "submit_diagnosis"]


@then("all three specialists ran")
def all_ran(ctx):
    assert {e["agent"] for e in ctx["events"] if e["event"] == "start"} == {"logs", "metrics", "knowledge"}


@then("their runs overlapped in time")
def overlapped(ctx):
    starts = [e["ts"] for e in ctx["events"] if e["event"] == "start"]
    ends = [e["ts"] for e in ctx["events"] if e["event"] == "end"]
    assert max(starts) < min(ends)


@then(parsers.parse("each specialist returned at most {n:d} Findings"))
def max_findings(ctx, n):
    for role in ("logs", "metrics", "knowledge"):
        assert 0 < sum(1 for e in ctx["events"] if e["event"] == "finding" and e["agent"] == role) <= n


@then("every Finding has a claim, a confidence and citations")
def finding_fields(ctx):
    for e in ctx["events"]:
        if e["event"] == "finding":
            assert e["claim"] and 0 <= e["confidence"] <= 1 and e["citations"]


def _passes(events):
    """Tool calls per (agent, pass) where pass 0 is the parallel run and pass 1 is the follow-up."""
    counts, current = {}, {}
    for e in events:
        if e["event"] == "start":
            current[e["agent"]] = 1 if e["followup"] else 0
        elif e["event"] == "tool_call":
            key = (e["agent"], current[e["agent"]])
            counts[key] = counts.get(key, 0) + 1
    return counts


@then(parsers.parse("no specialist executed more than {n:d} tool calls in its first pass"))
def first_pass(ctx, n):
    counts = _passes(ctx["events"])
    assert all(v <= n for (a, p), v in counts.items() if p == 0) and len([k for k in counts if k[1] == 0]) == 3


@then(parsers.parse("the follow-up executed at most {n:d} tool calls"))
def followup_pass(ctx, n):
    counts = _passes(ctx["events"])
    assert any(p == 1 for _, p in counts) and all(v <= n for (a, p), v in counts.items() if p == 1)


@then(parsers.parse("the total across the graph is at most {n:d}, the same as the single agent"))
def total(ctx, n):
    assert ctx["out"]["usage"]["tool_calls"] <= n


@then("the result is a valid Diagnosis")
def valid(ctx):
    assert isinstance(ctx["out"]["diagnosis"], Diagnosis)


@then("its citations are a subset of the citations in the specialists' findings")
def subset(ctx):
    handed = {c["ref"] for e in ctx["events"] if e["event"] == "finding" for c in e["citations"]}
    refs = {c.ref for c in ctx["out"]["diagnosis"].citations}
    assert refs <= handed and "L999999" not in refs


@then(parsers.parse("the coordinator issued exactly {n:d} follow-up to one specialist"))
def one_followup(ctx, n):
    assert sum(1 for e in ctx["events"] if e["event"] == "followup") == n


@then("no second follow-up round happened")
def no_second(ctx):
    assert sum(1 for e in ctx["events"] if e["event"] == "start" and e["followup"]) == 1


@then("the trace records which evidence ids specialists saw and which they handed off")
def handoff(ctx):
    u = ctx["out"]["usage"]
    assert u["log_ids_seen"] > 0 and 0 < u["log_ids_handed_off"] <= u["log_ids_seen"]
