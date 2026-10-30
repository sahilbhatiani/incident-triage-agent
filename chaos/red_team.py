"""Red-team Chaos Agent: proposes ChaosSpecs designed to fool the triage agents.

It may only emit a validated ChaosSpec; the simulator renders it, so labels stay deterministic.
"""

from __future__ import annotations


def propose_specs(llm, failures: list[dict], n: int = 6):
    raise NotImplementedError
