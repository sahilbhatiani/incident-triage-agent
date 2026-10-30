"""Step definitions for chaos_agent.feature."""

import json

from pytest_bdd import given, parsers, scenarios, then, when

from chaos.red_team import propose_specs
from sim.render import AGENT_VISIBLE, render
from tests.conftest import ScriptedChatModel, tool_call
from triage.schemas import ChaosSpec

scenarios("chaos_agent.feature")

VALID = [
    {"fault": "db_pool_saturation", "service": "postgres", "onset_min": 30, "severity": 0.4,
     "red_herrings": [{"kind": "cpu_spike", "service": "payments", "at_min": 25}], "noise": 0.3},
    {"fault": "memory_leak", "service": "inventory", "onset_min": 12, "severity": 0.6,
     "red_herrings": [{"kind": "unrelated_deploy", "service": "orders", "at_min": 10}], "noise": 0.2},
    {"fault": "cache_stampede", "service": "redis", "onset_min": 20, "severity": 0.3, "red_herrings": [], "noise": 0.4},
]


def _llm(ctx, proposals):
    def responder(messages, bound):
        ctx["prompt"] = messages[-1].content
        return tool_call("propose_incidents", {"proposals": proposals})
    return ScriptedChatModel(responder=responder)


@given(parsers.parse("a scripted fake LLM that proposes {n:d} specs"))
def proposes_n(ctx, n):
    ctx["llm"] = _llm(ctx, VALID[:n])
    ctx["n"] = n


@given(parsers.parse('a scripted fake LLM that proposes a spec with fault "{fault}"'))
def proposes_bad(ctx, fault):
    ctx["llm"] = _llm(ctx, [{**VALID[0], "fault": fault}])
    ctx["n"] = 1


@given("a valid ChaosSpec proposed by the red team")
def valid_spec(ctx):
    ctx["specs"], _, _ = propose_specs(_llm(ctx, VALID[:1]), [], 1)


@given(parsers.parse('past failures where approaches confused "{a}" with "{b}"'))
def failures(ctx, a, b):
    ctx["failures"] = [f"std-02a: truth db_pool_saturation on {b}; single said downstream_timeout on {a}"]
    ctx["llm"] = _llm(ctx, VALID[:1])
    ctx["n"] = 1


@when("the red team proposes specs from past failures")
def propose(ctx):
    ctx["specs"], ctx["rejected"], _ = propose_specs(ctx["llm"], ctx.get("failures", []), ctx["n"])


@when("I render it into the adversarial split")
def render_adv(ctx, tmp_path):
    spec = ctx["specs"][0]
    ctx["a"] = render(spec, tmp_path / "a" / "adversarial")
    ctx["b"] = render(spec, tmp_path / "b" / "adversarial")


@then(parsers.parse("I get {n:d} valid ChaosSpec objects"))
def n_valid(ctx, n):
    assert len(ctx["specs"]) == n and all(isinstance(s, ChaosSpec) for s in ctx["specs"])


@then("that proposal is dropped and reported as rejected")
def dropped(ctx):
    assert ctx["specs"] == [] and len(ctx["rejected"]) == 1


@then("its label equals the spec's fault and service")
def label_matches(ctx):
    label = json.loads((ctx["a"] / "label.json").read_text())
    s = ctx["specs"][0]
    assert (label["fault"], label["service"]) == (s.fault, s.service)


@then("rendering it again gives an identical incident")
def identical(ctx):
    for f in AGENT_VISIBLE:
        assert (ctx["a"] / f).read_bytes() == (ctx["b"] / f).read_bytes()


@then("the prompt sent to the LLM contains those failure summaries")
def prompt_has(ctx):
    assert ctx["failures"][0] in ctx["prompt"]
