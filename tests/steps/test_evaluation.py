"""Step definitions for evaluation.feature."""

import json

import pandas as pd
from pytest_bdd import given, parsers, scenarios, then, when

from eval.judge import JudgeVerdict, judge
from eval.report import summarise
from eval.run import RESULT_COLUMNS, run_matrix
from eval.score import ablate_key_evidence, is_correct
from eval.verify import verify_citations
from sim.render import render
from tests.conftest import ScriptedChatModel, tool_call
from triage.schemas import ChaosSpec, Citation, Diagnosis, Label

scenarios("evaluation.feature")


def _label(d):
    return Label.model_validate_json((d / "label.json").read_text())


def _diag(fault="db_pool_saturation", service="postgres", citations=()):
    return Diagnosis(fault=fault, service=service, explanation="x", citations=list(citations), confidence=0.7)


@given(parsers.parse('a Diagnosis naming "{fault}" on "{service}"'))
def diagnosis_named(ctx, fault, service):
    ctx["diag"] = _diag(fault, service)


@given(parsers.parse('a Diagnosis citing log "{ref}" which does not exist'))
def diag_fake_log(ctx, ref):
    ctx["diag"] = _diag(citations=[Citation(kind="log", ref=ref)])


@given(parsers.parse('a Diagnosis citing metric "{ref}"'))
def diag_metric(ctx, ref):
    ctx["diag"] = _diag(citations=[Citation(kind="metric", ref=ref)])


@given(parsers.parse("a Diagnosis citing one of the label's key evidence log ids and \"{series}\" over the fault window"))
def diag_real(ctx, series):
    label = _label(ctx["incident_dir"])
    ctx["diag"] = _diag(citations=[Citation(kind="log", ref=label.key_evidence_ids[0]),
                                   Citation(kind="metric", ref=f"{series}@{label.onset_ts}-{label.onset_ts + 600}")])


@given("a scripted fake judge LLM")
def fake_judge(ctx):
    verdict = {"root_cause_match": "correct", "evidence_support": 4, "next_steps_safe": True, "rationale": "ok"}
    ctx["judge_llm"] = ScriptedChatModel(responder=lambda m, b: tool_call("JudgeVerdict", verdict))


@given(parsers.parse("{n:d} incidents, approaches single and multi, and {s:d} seeds"))
def matrix_inputs(ctx, tmp_path, n, s):
    ctx["dirs"] = [render(ChaosSpec(incident_id=f"m{i}", fault="memory_leak", service="payments", onset_min=10,
                                    severity=0.8, seed=i), tmp_path / "standard") for i in range(n)]
    ctx["seeds"] = list(range(s))
    ctx["calls"] = 0

    def agent_fn(d, approach, seed):
        ctx["calls"] += 1
        return {"diagnosis": _diag("memory_leak", "payments"),
                "usage": {"tokens_in": 10, "tokens_out": 2, "cost_usd": 0.001, "latency_s": 0.1, "tool_calls": 3}}
    ctx["agent_fn"] = agent_fn


@given("a results.csv with rows for both approaches")
def results_rows(ctx):
    rows = []
    for a, correct in (("single", [1, 1, 0]), ("multi", [1, 0, 0])):
        for i, c in enumerate(correct):
            rows.append({"split": "standard", "approach": a, "correct": bool(c), "confidence": 0.8,
                         "citation_rate": 0.9, "cost_usd": 0.01, "latency_s": 5 + i, "tokens_in": 1000,
                         "tokens_out": 100, "tool_calls": 8, "judge_match": "correct", "judge_support": 4,
                         "judge_safe": True})
    ctx["df"] = pd.DataFrame(rows)


@when("I verify its citations")
def verify(ctx):
    ctx["ver"] = verify_citations(ctx["diag"], ctx["incident_dir"], {})


@when("the judge scores a Diagnosis against the label")
def run_judge(ctx):
    ctx["verdict"] = judge(ctx["judge_llm"], _diag(), _label(ctx["incident_dir"]), "evidence")


@when("I run the evaluation matrix with fake agents")
def run_mtx(ctx, tmp_path):
    ctx["cache"] = tmp_path / "cache"
    ctx["df"] = run_matrix(ctx["dirs"], ["single", "multi"], ctx["seeds"], ctx["cache"], ctx["agent_fn"],
                           kb_chunks={}, out_csv=tmp_path / "results.csv")


@when("I create the ablated copy of the incident")
def ablate(ctx, tmp_path):
    ctx["orig_logs"] = (ctx["incident_dir"] / "logs.jsonl").read_text()
    ctx["ablated"] = ablate_key_evidence(ctx["incident_dir"], tmp_path / "ablated")


@when("I build the report")
def report(ctx):
    ctx["summary"] = summarise(ctx["df"])


@then("it is scored correct")
def scored_correct(ctx):
    assert is_correct(ctx["diag"], _label(ctx["incident_dir"]))


@then(parsers.parse('a Diagnosis naming "{fault}" on "{service}" is scored incorrect'))
def scored_incorrect(ctx, fault, service):
    assert not is_correct(_diag(fault, service), _label(ctx["incident_dir"]))


@then(parsers.parse('a Diagnosis naming "unknown" is scored incorrect'))
def unknown_incorrect(ctx):
    assert not is_correct(_diag("unknown", "unknown"), _label(ctx["incident_dir"]))


@then("that citation is invalid and the valid-citation rate is below 1")
def invalid_log(ctx):
    assert ctx["ver"]["invalid"] == 1 and ctx["ver"]["rate"] < 1


@then("that citation is invalid because the window has no anomaly")
def invalid_metric(ctx):
    assert ctx["ver"]["details"][0]["reason"] == "window has no anomaly"


@then(parsers.parse("the valid-citation rate is {r:d}"))
def rate_is(ctx, r):
    assert ctx["ver"]["rate"] == r, ctx["ver"]["details"]


@then("the verdict has root_cause_match in correct/partial/incorrect, evidence_support from 1 to 5, and next_steps_safe true or false")
def verdict_ok(ctx):
    v = ctx["verdict"]
    assert isinstance(v, JudgeVerdict) and v.root_cause_match in ("correct", "partial", "incorrect")
    assert 1 <= v.evidence_support <= 5 and isinstance(v.next_steps_safe, bool)


@then(parsers.parse("results.csv has {n:d} rows with columns {cols}"))
def csv_rows(ctx, tmp_path, n, cols):
    df = pd.read_csv(tmp_path / "results.csv")
    assert len(df) == n
    assert {c.strip() for c in cols.split(",")} <= set(df.columns) and set(RESULT_COLUMNS) <= set(df.columns)


@then("running it again executes no agents")
def cached(ctx):
    before = ctx["calls"]
    run_matrix(ctx["dirs"], ["single", "multi"], ctx["seeds"], ctx["cache"], ctx["agent_fn"], kb_chunks={})
    assert ctx["calls"] == before


@then("none of the label's key_evidence_ids remain in its logs")
def ablated(ctx):
    keys = set(_label(ctx["incident_dir"]).key_evidence_ids)
    ids = {json.loads(l)["id"] for l in (ctx["ablated"] / "logs.jsonl").read_text().splitlines()}
    assert keys and not (keys & ids)


@then("the original incident is unchanged")
def orig_unchanged(ctx):
    assert (ctx["incident_dir"] / "logs.jsonl").read_text() == ctx["orig_logs"]


@then("it shows accuracy as n/N, mean citation rate, mean cost, p50 latency and calibration per approach and split")
def report_cols(ctx):
    s = ctx["summary"]
    assert set(s["approach"]) == {"single", "multi"}
    assert {"accuracy", "citation_rate", "cost_usd_mean", "latency_p50_s", "ece"} <= set(s.columns)
    assert s.set_index("approach").loc["single", "accuracy"] == "2/3"
