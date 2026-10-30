"""World model: service dependency graph and baseline metric generation."""

from __future__ import annotations

SERVICES = ["gateway", "orders", "payments", "inventory", "redis", "postgres"]

# caller -> callee ("calls") edges; symptoms propagate against these arrows.
EDGES = [
    ("gateway", "orders"),
    ("orders", "payments"),
    ("orders", "inventory"),
    ("orders", "redis"),
    ("payments", "postgres"),
    ("inventory", "postgres"),
]

METRICS = ["rps", "p95_latency_ms", "error_rate", "cpu", "mem", "db_pool_used"]
STEP_SECONDS = 15
WINDOW_MINUTES = 60


def callers_of(service: str) -> list[str]:
    """Services that call `service` (one hop upstream)."""
    raise NotImplementedError


def baseline(seed: int):
    """Return a DataFrame of healthy metrics for every service over the window."""
    raise NotImplementedError
