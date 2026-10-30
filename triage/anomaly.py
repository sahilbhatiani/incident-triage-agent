"""Cheap, deterministic change-point detector (no LLM) shared by tools, verifier and tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

BASELINE_STEPS = 20  # first 5 minutes at 15 s resolution
Z_THRESHOLD = 6.0
CONSECUTIVE = 3


def detect(t: np.ndarray, values: np.ndarray) -> dict | None:
    """Return {start, end, direction, peak_z, baseline_mean} for the first sustained deviation, else None."""
    base = values[:BASELINE_STEPS]
    mean = float(base.mean())
    std = max(float(base.std()), 0.02 * abs(mean), 1e-4)
    z = (values - mean) / std
    hot = np.abs(z) > Z_THRESHOLD
    run = 0
    for i, h in enumerate(hot):
        run = run + 1 if h else 0
        if run == CONSECUTIVE:
            s = i - CONSECUTIVE + 1
            after = np.where(~hot[s:])[0]
            e = s + int(after[0]) - 1 if len(after) else len(values) - 1
            seg = z[s:e + 1]
            return {
                "start": int(t[s]),
                "end": int(t[e]),
                "direction": "up" if seg.mean() > 0 else "down",
                "peak_z": round(float(np.abs(seg).max()), 1),
                "baseline_mean": round(mean, 4),
            }
    return None


def anomalies(metrics: pd.DataFrame, service: str | None = None, metric_names=None) -> list[dict]:
    """Change points for every (service, metric) series, sorted by start time."""
    from sim.world import METRICS

    out = []
    names = metric_names or METRICS
    services = [service] if service else sorted(metrics["service"].unique())
    for svc in services:
        sub = metrics[metrics["service"] == svc].sort_values("t")
        for m in names:
            hit = detect(sub["t"].to_numpy(), sub[m].to_numpy())
            if hit:
                out.append({"service": svc, "metric": m, **hit})
    return sorted(out, key=lambda a: (a["start"], -a["peak_z"]))
