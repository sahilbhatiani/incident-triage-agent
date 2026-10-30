"""Event bus: records tool calls, findings and token usage to JSONL and a live queue."""

from __future__ import annotations


class Tracer:
    def __init__(self, run_id: str, out_dir=None, live_queue=None):
        raise NotImplementedError

    def emit(self, agent: str, event: str, **payload):
        raise NotImplementedError

    def summary(self) -> dict:
        """Tokens in/out, tool calls, wall-clock and estimated $ cost."""
        raise NotImplementedError
