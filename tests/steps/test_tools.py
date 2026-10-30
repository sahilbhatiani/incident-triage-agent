"""Step definitions for tools.feature."""

import hashlib
import json

from pytest_bdd import given, parsers, scenarios, then, when

from triage.tools import IncidentTools
from triage.tracing import Tracer

scenarios("tools.feature")


def _snapshot(d):
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(d.iterdir())}


def _call_all(tools):
    return [
        tools.query_logs(limit=50),
        tools.query_logs(level="ERROR"),
        tools.get_metric("postgres", "db_pool_used"),
        tools.get_metric("gateway", "error_rate"),
        tools.list_anomalies(),
        tools.search_kb("database connections exhausted"),
        tools.search_kb("timeout acquiring connection"),
        tools.get_topology(),
    ]


@given("tools bound to that incident")
def bound_tools(ctx, kb_retriever):
    ctx["tools"] = IncidentTools(ctx["incident_dir"], kb_retriever)


@given("a tracer attached to the tools")
def attach_tracer(ctx):
    ctx["tracer"] = Tracer("t")
    ctx["tools"].tracer = ctx["tracer"]


@when(parsers.parse('I call query_logs with service "{service}" and level "{level}"'))
def call_logs(ctx, service, level):
    ctx["out"] = ctx["tools"].query_logs(service=service, level=level)


@when(parsers.parse('I call query_logs with contains "{text}" between minute {a:d} and minute {b:d}'))
def call_logs_window(ctx, text, a, b):
    ctx["out"] = ctx["tools"].query_logs(contains=text, t0=a * 60, t1=b * 60)
    ctx["window"] = (a * 60, b * 60, text)


@when(parsers.parse('I call get_metric for "{service}" "{metric}"'))
def call_metric(ctx, service, metric):
    ctx["out"] = ctx["tools"].get_metric(service, metric)


@when("I call list_anomalies")
def call_anoms(ctx):
    ctx["out"] = ctx["tools"].list_anomalies()


@when("I call get_topology")
def call_topo(ctx):
    ctx["out"] = ctx["tools"].get_topology()


@when("I call every tool with broad arguments")
@when("I call every tool")
def call_every(ctx):
    ctx["before"] = _snapshot(ctx["incident_dir"])
    ctx["outs"] = _call_all(ctx["tools"])


@when("I call query_logs and get_metric")
def call_two(ctx):
    ctx["tools"].query_logs(service="postgres")
    ctx["tools"].get_metric("postgres", "cpu")


@then(parsers.parse("I get at most {n:d} lines"))
def at_most_lines(ctx, n):
    assert 0 < len(ctx["out"]["lines"]) <= n


@then("every line has an id, timestamp, service, level and message")
def line_fields(ctx):
    for l in ctx["out"]["lines"]:
        assert {"id", "t", "time", "service", "level", "msg"} <= l.keys()


@then(parsers.parse('every returned line contains "{text}" and falls inside that window'))
def lines_in_window(ctx, text):
    t0, t1, _ = ctx["window"]
    assert ctx["out"]["lines"]
    for l in ctx["out"]["lines"]:
        assert text in l["msg"].lower() and t0 <= l["t"] <= t1


@then(parsers.parse("I get at most {n:d} points"))
def at_most_points(ctx, n):
    assert 0 < len(ctx["out"]["points"]) <= n


@then("a summary with min, max, mean and baseline_mean")
def summary(ctx):
    assert {"min", "max", "mean", "baseline_mean"} <= ctx["out"]["summary"].keys()


@then(parsers.parse('the results include "{service}" "{metric}" with a start near minute {m:d}'))
def anomaly_found(ctx, service, metric, m):
    hits = [a for a in ctx["out"]["anomalies"] if a["service"] == service and a["metric"] == metric]
    assert hits and abs(hits[0]["start"] - m * 60) <= 120


@then(parsers.parse("I get the {n:d} dependency edges"))
def edges(ctx, n):
    assert len(ctx["out"]["edges"]) == n


@then(parsers.parse('no output contains the strings "{a}", "{b}" or "{c}"'))
def no_leak(ctx, a, b, c):
    blob = json.dumps(ctx["outs"]).lower()
    for s in (a, b, c):
        assert s.lower() not in blob, s


@then("the incident folder is unchanged on disk")
def unchanged(ctx):
    assert _snapshot(ctx["incident_dir"]) == ctx["before"]


@then(parsers.parse("the tracer recorded {n:d} tool_call events with their arguments"))
def traced(ctx, n):
    calls = [e for e in ctx["tracer"].events if e["event"] == "tool_call"]
    assert len(calls) == n and all("args" in e for e in calls)
