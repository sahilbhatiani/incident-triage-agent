"""Step definitions for single_agent.feature."""

from pytest_bdd import given, parsers, scenarios, then, when

from tests.conftest import ScriptedChatModel, tool_call
from tests.scripts import GOOD, forever, sequence
from triage.run import make_llm, triage_incident
from triage.schemas import Diagnosis
from triage.single import build_single_agent
from triage.tools import IncidentTools
from triage.tracing import Tracer

scenarios("single_agent.feature")


@given("a scripted fake LLM")
def scripted(ctx):
    ctx["llm"] = ScriptedChatModel(responder=sequence(tool_call("submit_diagnosis", GOOD)))


@given(parsers.parse('the fake LLM calls list_anomalies, then query_logs, then answers fault "{fault}" on "{service}"'))
def script_happy(ctx, fault, service):
    ctx["llm"] = ScriptedChatModel(responder=sequence(
        tool_call("list_anomalies"),
        tool_call("query_logs", {"service": service, "level": "ERROR", "limit": 5}),
        tool_call("submit_diagnosis", {**GOOD, "fault": fault, "service": service})))


@given("the fake LLM keeps requesting tool calls forever")
def script_forever(ctx):
    ctx["llm"] = ScriptedChatModel(responder=forever())


@given(parsers.parse('the fake LLM answers with fault "{fault}", which is not in the taxonomy'))
def script_bad(ctx, fault):
    ctx["llm"] = ScriptedChatModel(responder=sequence(tool_call("submit_diagnosis", {**GOOD, "fault": fault})))


@given("the real agent model")
def real_model(ctx):
    ctx["llm"] = make_llm()
    ctx["live"] = True


@when("the single agent triages the incident")
def run_single(ctx, kb_retriever):
    ctx["tracer"] = Tracer("single-test")
    retriever = None if ctx.get("live") else kb_retriever
    ctx["out"] = triage_incident(ctx["incident_dir"], "single", ctx["llm"], retriever, ctx["tracer"])


@when("I build the single agent")
def build(ctx, kb_retriever):
    ctx["agent"] = build_single_agent(ctx["llm"], IncidentTools(ctx["incident_dir"], kb_retriever))


@then(parsers.parse('the result is a valid Diagnosis naming "{fault}" on "{service}"'))
def diag_named(ctx, fault, service):
    d = ctx["out"]["diagnosis"]
    assert isinstance(d, Diagnosis) and (d.fault, d.service) == (fault, service)


@then("the result is a valid Diagnosis")
def diag_valid(ctx):
    assert isinstance(ctx["out"]["diagnosis"], Diagnosis)


@then(parsers.parse('the result is a valid Diagnosis with fault "{fault}"'))
def diag_fault(ctx, fault):
    assert ctx["out"]["diagnosis"].fault == fault


@then("the diagnosis has at least one citation")
def has_citation(ctx):
    assert ctx["out"]["diagnosis"].citations


@then("it is bound to query_logs, get_metric, list_anomalies, search_kb and get_topology")
def bound(ctx):
    assert sorted(ctx["agent"].tool_names) == sorted(["query_logs", "get_metric", "list_anomalies", "search_kb", "get_topology"])


@then(parsers.parse("at most {n:d} tool calls are executed"))
def budget(ctx, n):
    assert ctx["out"]["usage"]["tool_calls"] <= n


@then("the agent is forced to answer with a Diagnosis")
def forced(ctx):
    assert isinstance(ctx["out"]["diagnosis"], Diagnosis)


@then("the trace summary reports tool calls, tokens and wall-clock time")
def usage(ctx):
    u = ctx["out"]["usage"]
    assert u["tool_calls"] == 2 and u["tokens_in"] > 0 and u["latency_s"] >= 0
