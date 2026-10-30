"""Red-team Chaos Agent: proposes ChaosSpecs designed to fool the triage agents.

It may only emit ChaosSpec parameters. Invalid proposals are dropped, never repaired, and the
deterministic simulator renders the valid ones, so every adversarial label is still a fact.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, ValidationError

from sim.render import render
from sim.world import EDGES
from triage.schemas import ChaosSpec

RED_TEAM_PROMPT = """You are a red-team engineer designing production incidents that are hard to diagnose.
A team of triage agents reads logs, metrics and runbooks and must name the root-cause fault and service.

Topology (caller -> callee): {edges}
Symptoms propagate upstream from the failing service to its callers with lag.

Fault types and the services they can originate on:
- bad_deploy: orders, payments, inventory
- db_pool_saturation: postgres
- downstream_timeout: payments, inventory
- memory_leak: orders, payments, inventory
- cache_stampede: redis
Red herring kinds: cpu_spike, noisy_warning, unrelated_deploy, gc_logs, disk_warning (each on a service, at a minute 0-59).
Parameters: onset_min 5-50, severity 0.1-1.0 (lower is subtler), noise 0.0-1.0.

Past failures of the triage agents:
{failures}

Propose {n} incidents that exploit these weaknesses: plant red herrings that mimic the wrong diagnosis,
place them earlier than the real onset, keep the real fault subtle. Call propose_incidents once."""


class Proposal(BaseModel):
    fault: str
    service: str
    onset_min: int
    severity: float
    red_herrings: list[dict] = []
    noise: float = 0.2
    rationale: str = ""


class ProposalBatch(BaseModel):
    proposals: list[Proposal] = Field(description="the incident designs")


def summarise_failures(results: pd.DataFrame, limit: int = 10) -> list[str]:
    wrong = results[~results["correct"].astype(bool)]
    out = []
    for _, r in wrong.head(limit).iterrows():
        out.append(f"{r['incident']}: truth {r['fault_true']} on {r['service_true']}; {r['approach']} said "
                   f"{r['fault_pred']} on {r['service_pred']}")
    return out


def propose_specs(llm, failures: list[str], n: int = 6, start_index: int = 1):
    """Return (valid ChaosSpecs, rejected proposals with reasons, the prompt sent)."""
    tool = StructuredTool.from_function(func=lambda **kw: "ok", name="propose_incidents", args_schema=ProposalBatch,
                                        description="Submit incident designs.")
    prompt = RED_TEAM_PROMPT.format(edges=", ".join(f"{a}->{b}" for a, b in EDGES),
                                    failures="\n".join(f"- {f}" for f in failures) or "- none recorded yet", n=n)
    msg = llm.bind_tools([tool], tool_choice="propose_incidents").invoke(
        [SystemMessage(content="You design adversarial test incidents."), HumanMessage(content=prompt)])
    raw = next((tc["args"].get("proposals", []) for tc in msg.tool_calls if tc["name"] == "propose_incidents"), [])
    specs, rejected = [], []
    for i, p in enumerate(raw[:n]):
        try:
            p = dict(p)
            p.pop("rationale", None)
            idx = start_index + len(specs)
            specs.append(ChaosSpec(incident_id=f"adv-{idx:02d}", seed=900 + idx, **p))
        except (ValidationError, TypeError) as e:
            rejected.append({"proposal": p, "reason": str(e).splitlines()[0]})
    return specs, rejected, prompt


def main():
    from triage.run import make_llm

    ap = argparse.ArgumentParser(description="Generate the adversarial split")
    ap.add_argument("--results", default="results/results.csv")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out", default="data/incidents/adversarial")
    args = ap.parse_args()
    failures = summarise_failures(pd.read_csv(args.results)) if Path(args.results).exists() else []
    specs, rejected, _ = propose_specs(make_llm(os.getenv("JUDGE_MODEL", "gpt-4.1")), failures, args.n)
    for s in specs:
        render(s, Path(args.out))
    Path(args.out, "_red_team_log.json").write_text(json.dumps(
        {"failures": failures, "accepted": [s.model_dump() for s in specs], "rejected": rejected}, indent=2))
    print(f"rendered {len(specs)} adversarial incidents, rejected {len(rejected)}")


if __name__ == "__main__":
    main()
