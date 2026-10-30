"""World model: service dependency graph and baseline metric generation."""

from __future__ import annotations

import numpy as np
import pandas as pd

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
N_STEPS = WINDOW_MINUTES * 60 // STEP_SECONDS

# Healthy operating point per service.
BASELINE = {
    "gateway":   {"rps": 220, "p95_latency_ms": 120, "error_rate": 0.002, "cpu": 0.35, "mem": 0.45, "db_pool_used": 0.0},
    "orders":    {"rps": 200, "p95_latency_ms": 95,  "error_rate": 0.002, "cpu": 0.40, "mem": 0.50, "db_pool_used": 0.0},
    "payments":  {"rps": 70,  "p95_latency_ms": 140, "error_rate": 0.001, "cpu": 0.30, "mem": 0.48, "db_pool_used": 0.0},
    "inventory": {"rps": 130, "p95_latency_ms": 45,  "error_rate": 0.001, "cpu": 0.28, "mem": 0.42, "db_pool_used": 0.0},
    "redis":     {"rps": 450, "p95_latency_ms": 2,   "error_rate": 0.0005, "cpu": 0.20, "mem": 0.60, "db_pool_used": 0.0},
    "postgres":  {"rps": 320, "p95_latency_ms": 12,  "error_rate": 0.0005, "cpu": 0.38, "mem": 0.65, "db_pool_used": 0.30},
}

# Relative noise per metric, scaled by spec.noise.
NOISE_SCALE = {"rps": 0.04, "p95_latency_ms": 0.06, "error_rate": 0.3, "cpu": 0.05, "mem": 0.01, "db_pool_used": 0.05}


def callers_of(service: str) -> list[str]:
    """Services that call `service` (one hop upstream)."""
    return [a for a, b in EDGES if b == service]


def upstream_hops(service: str) -> dict[str, int]:
    """Every service upstream of `service` with its hop distance (BFS)."""
    hops, frontier = {}, [service]
    depth = 0
    while frontier:
        depth += 1
        nxt = []
        for s in frontier:
            for c in callers_of(s):
                if c not in hops:
                    hops[c] = depth
                    nxt.append(c)
        frontier = nxt
    return hops


def timestamps() -> np.ndarray:
    return np.arange(N_STEPS) * STEP_SECONDS


def baseline(rng: np.random.Generator, noise: float) -> pd.DataFrame:
    """Healthy metrics for every service: one row per (t, service), one column per metric."""
    t = timestamps()
    wave = 1 + 0.05 * np.sin(2 * np.pi * t / 3600)  # gentle traffic cycle
    frames = []
    for svc in SERVICES:
        cols = {"t": t, "service": svc}
        for m in METRICS:
            base = BASELINE[svc][m]
            jitter = rng.normal(0, NOISE_SCALE[m] * max(noise, 0.02), size=len(t))
            series = base * (wave if m in ("rps", "cpu") else 1) * (1 + jitter)
            cols[m] = np.clip(series, 0, None)
        frames.append(pd.DataFrame(cols))
    return pd.concat(frames, ignore_index=True)
