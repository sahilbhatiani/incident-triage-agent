"""Step definitions for simulator.feature."""

import json
import re

import pandas as pd
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from sim.render import AGENT_VISIBLE, render, standard_specs
from sim.world import EDGES
from triage.anomaly import anomalies
from triage.schemas import ChaosSpec, RedHerring

scenarios("simulator.feature")


@pytest.fixture
def ctx():
    return {}


def _spec(fault, service, minute, seed, **kw):
    return ChaosSpec(incident_id="t1", fault=fault, service=service, onset_min=minute, severity=0.8, seed=seed, **kw)


def _metrics(d):
    return pd.read_parquet(d / "metrics.parquet")


def _logs(d):
    return [json.loads(l) for l in (d / "logs.jsonl").read_text().splitlines()]


def _first(d, service, metric):
    hits = [a for a in anomalies(_metrics(d), service) if a["metric"] == metric]
    return hits[0] if hits else None


@given(parsers.parse("the service topology {topology}"))
def topology(topology):
    assert len(EDGES) == 6


@given(parsers.parse('a ChaosSpec with fault "{fault}" on "{service}" at minute {minute:d} with seed {seed:d}'))
def a_spec(ctx, fault, service, minute, seed):
    ctx["spec"] = _spec(fault, service, minute, seed)


@given(parsers.parse('a ChaosSpec with fault "{fault}" on "{service}" and a "{kind}" red herring on "{rh_service}" at minute {rh_min:d}'))
def a_spec_with_herring(ctx, fault, service, kind, rh_service, rh_min):
    ctx["spec"] = _spec(fault, service, 25, 5, red_herrings=[RedHerring(kind=kind, service=rh_service, at_min=rh_min)])


@given("a rendered incident")
def a_rendered_incident(ctx, tmp_path):
    ctx["dir"] = render(standard_specs()[3], tmp_path)


@when("I render it twice into separate folders")
def render_twice(ctx, tmp_path):
    ctx["a"] = render(ctx["spec"], tmp_path / "a")
    ctx["b"] = render(ctx["spec"], tmp_path / "b")


@when(parsers.parse("I render it with seed {s1:d} and again with seed {s2:d}"))
def render_two_seeds(ctx, tmp_path, s1, s2):
    ctx["a"] = render(ctx["spec"].model_copy(update={"seed": s1}), tmp_path / "a")
    ctx["b"] = render(ctx["spec"].model_copy(update={"seed": s2}), tmp_path / "b")


@when("I render it")
def render_once(ctx, tmp_path):
    ctx["dir"] = render(ctx["spec"], tmp_path)


@when("I generate the standard set")
def gen_standard(ctx):
    ctx["specs"] = standard_specs()


@then("the logs, metrics and alert files are byte-identical")
def byte_identical(ctx):
    for f in AGENT_VISIBLE:
        assert (ctx["a"] / f).read_bytes() == (ctx["b"] / f).read_bytes(), f


@then("the metrics differ")
def metrics_differ(ctx):
    assert not _metrics(ctx["a"]).equals(_metrics(ctx["b"]))


@then(parsers.parse('both labels name fault "{fault}" on service "{service}"'))
def labels_match(ctx, fault, service):
    for d in (ctx["a"], ctx["b"]):
        label = json.loads((d / "label.json").read_text())
        assert (label["fault"], label["service"]) == (fault, service)


@then(parsers.parse('the metric "{metric}" on "{service}" shifts after minute {minute:d} compared with its baseline'))
def metric_shifts(ctx, metric, service, minute):
    hit = _first(ctx["dir"], service, metric)
    assert hit is not None and hit["start"] >= minute * 60


@then(parsers.parse('at least one log line on "{service}" contains "{text}"'))
def log_contains(ctx, service, text):
    assert any(l["service"] == service and text.lower() in l["msg"].lower() for l in _logs(ctx["dir"]))


@then(parsers.parse('"{later}" shows elevated {metric} starting later than "{earlier}" shows its anomaly'))
def later_than_origin(ctx, later, metric, earlier):
    origin = min(a["start"] for a in anomalies(_metrics(ctx["dir"]), earlier))
    hit = _first(ctx["dir"], later, metric)
    assert hit is not None and hit["start"] > origin


@then(parsers.parse('"{later}" shows elevated {metric} starting later than "{earlier}"'))
def later_than(ctx, later, metric, earlier):
    e = min(a["start"] for a in anomalies(_metrics(ctx["dir"]), earlier))
    hit = _first(ctx["dir"], later, metric)
    assert hit is not None and hit["start"] > e


@then(parsers.parse('services not upstream of "{origin}", such as "{other}", stay within baseline'))
def unaffected(ctx, origin, other):
    assert anomalies(_metrics(ctx["dir"]), other) == []


@then(parsers.parse('"{service}" cpu is anomalous around minute {minute:d}'))
def cpu_anomalous(ctx, service, minute):
    hit = _first(ctx["dir"], service, "cpu")
    assert hit is not None and abs(hit["start"] - minute * 60) <= 60


@then(parsers.parse('the label still names "{service}" as the root-cause service'))
def label_service(ctx, service):
    assert json.loads((ctx["dir"] / "label.json").read_text())["service"] == service


@then("the incident folder contains alert.json, logs.jsonl, metrics.parquet and label.json")
def files_exist(ctx):
    for f in (*AGENT_VISIBLE, "label.json"):
        assert (ctx["dir"] / f).exists()


@then(parsers.parse('no agent-visible file contains the string "{text}"'))
def no_leak(ctx, text):
    assert text not in (ctx["dir"] / "alert.json").read_text()
    assert text not in (ctx["dir"] / "logs.jsonl").read_text()
    m = _metrics(ctx["dir"])
    assert text not in " ".join(m.columns) and text not in " ".join(m["service"].unique())


@then("label.json lists key_evidence_ids that exist in logs.jsonl")
def key_ids_exist(ctx):
    ids = {l["id"] for l in _logs(ctx["dir"])}
    keys = json.loads((ctx["dir"] / "label.json").read_text())["key_evidence_ids"]
    assert keys and set(keys) <= ids


@then(parsers.parse('every log line has an id matching "{pattern}" and ids are unique'))
def ids_valid(ctx, pattern):
    ids = [l["id"] for l in _logs(ctx["dir"])]
    assert all(re.fullmatch(r"L\d{6}", i) for i in ids)
    assert len(ids) == len(set(ids))


@then(parsers.parse("there are {n:d} incidents, {k:d} per fault type"))
def standard_counts(ctx, n, k):
    specs = ctx["specs"]
    assert len(specs) == n
    counts = pd.Series([s.fault for s in specs]).value_counts()
    assert len(counts) == 5 and (counts == k).all()
