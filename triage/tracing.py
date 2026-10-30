"""Event bus: records tool calls, findings and token usage to JSONL and a live queue."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

# USD per 1M tokens (input, output). Estimates; override with PRICE_<MODEL>="in,out".
PRICES = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}

LOG_ID = re.compile(r"L\d{6}")


def price(model: str) -> tuple[float, float]:
    env = os.getenv(f"PRICE_{model.upper().replace('-', '_').replace('.', '_')}")
    if env:
        a, b = env.split(",")
        return float(a), float(b)
    return PRICES.get(model, (0.0, 0.0))


class Tracer:
    def __init__(self, run_id: str, out_dir=None, live_queue=None, model: str = ""):
        self.run_id = run_id
        self.model = model
        self.events: list[dict] = []
        self.queue = live_queue
        self.path = Path(out_dir) / f"{run_id}.jsonl" if out_dir else None
        self.t_start = time.time()
        self._lock = threading.Lock()
        self.seen: dict[str, set[str]] = {}
        self.handed_off: dict[str, set[str]] = {}

    def emit(self, agent: str, event: str, **payload):
        ev = {"ts": round(time.time() - self.t_start, 3), "run_id": self.run_id, "agent": agent, "event": event, **payload}
        with self._lock:
            self.events.append(ev)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as f:
                    f.write(json.dumps(ev, default=str) + "\n")
        if self.queue is not None:
            self.queue.put(ev)
        return ev

    def llm(self, agent: str, usage: dict | None):
        usage = usage or {}
        self.emit(agent, "llm_call", tokens_in=usage.get("input_tokens", 0), tokens_out=usage.get("output_tokens", 0))

    def saw(self, agent: str, text: str):
        with self._lock:
            self.seen.setdefault(agent, set()).update(LOG_ID.findall(text))

    def handoff(self, agent: str, refs: list[str]):
        with self._lock:
            self.handed_off.setdefault(agent, set()).update(r for r in refs if LOG_ID.fullmatch(r))

    def summary(self) -> dict:
        """Tokens in/out, tool calls, wall-clock and estimated $ cost."""
        tin = sum(e.get("tokens_in", 0) for e in self.events if e["event"] == "llm_call")
        tout = sum(e.get("tokens_out", 0) for e in self.events if e["event"] == "llm_call")
        p_in, p_out = price(self.model)
        seen = set().union(*self.seen.values()) if self.seen else set()
        handed = set().union(*self.handed_off.values()) if self.handed_off else set()
        return {
            "tool_calls": sum(1 for e in self.events if e["event"] == "tool_call"),
            "llm_calls": sum(1 for e in self.events if e["event"] == "llm_call"),
            "tokens_in": tin,
            "tokens_out": tout,
            "cost_usd": round(tin / 1e6 * p_in + tout / 1e6 * p_out, 5),
            "latency_s": round(time.time() - self.t_start, 2),
            "log_ids_seen": len(seen),
            "log_ids_handed_off": len(handed),
        }
