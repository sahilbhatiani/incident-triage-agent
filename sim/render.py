"""Render a ChaosSpec into an incident folder: alert, logs, metrics and a sealed label."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from sim.faults import END, add_red_herrings, inject, propagate
from sim.world import METRICS, SERVICES, baseline
from triage.schemas import ChaosSpec, Label, RedHerring

# Files the tool layer may read. label.json and spec.json are sealed.
AGENT_VISIBLE = ("alert.json", "logs.jsonl", "metrics.parquet")

ENDPOINTS = {
    "gateway": "GET /api/cart", "orders": "POST /api/orders", "payments": "POST /api/payments/charge",
    "inventory": "GET /api/inventory/sku", "redis": "GET session:*", "postgres": "SELECT orders",
}


def _baseline_logs(rng) -> list[dict]:
    logs = []
    for svc in SERVICES:
        t = float(rng.uniform(0, 30))
        while t < END:
            ms = int(rng.integers(5, 120))
            logs.append({"t": int(t), "service": svc, "level": "INFO",
                         "msg": f"{ENDPOINTS[svc]} 200 in {ms}ms", "_key": False})
            if rng.random() < 0.04:
                logs.append({"t": int(t) + 1, "service": svc, "level": "WARN",
                             "msg": f"slow request {ENDPOINTS[svc]} took {int(rng.integers(400, 900))}ms", "_key": False})
            t += rng.uniform(40, 80)
    return logs


def _clock(t: int) -> str:
    return f"2026-10-30T09:{t // 60:02d}:{t % 60:02d}Z"


def build(spec: ChaosSpec):
    """Pure simulation: returns (metrics_df, logs, alert, label)."""
    rng = np.random.default_rng(spec.seed)
    df = baseline(rng, spec.noise)
    logs = _baseline_logs(rng)
    impact = inject(df, logs, spec, rng)
    starts = propagate(df, logs, spec, rng, impact)
    add_red_herrings(df, logs, spec, rng)

    logs = [l for l in logs if 0 <= l["t"] < END]
    logs.sort(key=lambda l: (l["t"], l["service"], l["level"], l["msg"]))
    for i, line in enumerate(logs, start=1):
        line["id"] = f"L{i:06d}"
    key_ids = [l["id"] for l in logs if l["_key"]]
    logs = [{"id": l["id"], "t": l["t"], "time": _clock(l["t"]), "service": l["service"],
             "level": l["level"], "msg": l["msg"]} for l in logs]

    df[METRICS] = df[METRICS].round(4)
    fired = starts.get("gateway", spec.onset_min * 60) + 60
    alert = {
        "alert_id": f"ALRT-{spec.incident_id}",
        "title": "gateway: 5xx error rate and p95 latency above SLO",
        "service": "gateway",
        "severity": "P2",
        "fired_at": _clock(min(fired, END - 1)),
        "fired_at_t": int(min(fired, END - 1)),
        "window": {"t0": 0, "t1": END},
    }
    label = Label(fault=spec.fault, service=spec.service, onset_ts=spec.onset_min * 60, key_evidence_ids=key_ids)
    return df, logs, alert, label


def render(spec: ChaosSpec, out_dir: Path) -> Path:
    """Deterministically build the incident for `spec` and write it to `out_dir/<id>/`."""
    df, logs, alert, label = build(spec)
    d = Path(out_dir) / spec.incident_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "alert.json").write_text(json.dumps(alert, indent=2))
    (d / "logs.jsonl").write_text("".join(json.dumps(l) + "\n" for l in logs))
    df.to_parquet(d / "metrics.parquet", index=False)
    (d / "label.json").write_text(label.model_dump_json(indent=2))
    (d / "spec.json").write_text(spec.model_dump_json(indent=2))
    return d


# Standard split: 5 faults x 3 variants of increasing difficulty.
_STANDARD = [
    ("bad_deploy", ["orders", "payments", "inventory"]),
    ("db_pool_saturation", ["postgres", "postgres", "postgres"]),
    ("downstream_timeout", ["payments", "inventory", "inventory"]),
    ("memory_leak", ["payments", "orders", "inventory"]),
    ("cache_stampede", ["redis", "redis", "redis"]),
]
_HERRINGS = [
    [],
    [("noisy_warning", "gateway", 8)],
    [("cpu_spike", "inventory", 12), ("unrelated_deploy", "payments", 14)],
]


def standard_specs() -> list[ChaosSpec]:
    specs = []
    for fi, (fault, services) in enumerate(_STANDARD):
        for v, svc in enumerate(services):
            herrings = [RedHerring(kind=k, service=s, at_min=m) for k, s, m in _HERRINGS[v] if s != svc]
            specs.append(ChaosSpec(
                incident_id=f"std-{fi + 1:02d}{chr(97 + v)}",
                fault=fault, service=svc,
                onset_min=[15, 22, 28][v],
                severity=[0.9, 0.7, 0.5][v],
                red_herrings=herrings,
                noise=[0.1, 0.15, 0.2][v],
                seed=100 + fi * 10 + v,
            ))
    return specs


def generate_standard_set(out_dir: Path) -> list[Path]:
    """Render the standard split: every fault type x 3 variants."""
    return [render(s, out_dir) for s in standard_specs()]


if __name__ == "__main__":
    paths = generate_standard_set(Path("data/incidents/standard"))
    print(f"rendered {len(paths)} incidents")
