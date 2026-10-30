"""Fault library and upstream propagation of symptoms.

Every function mutates the metrics frame and appends to the log list in place.
Log dicts carry a private `_key` flag marking key evidence; the renderer strips it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sim.world import BASELINE, STEP_SECONDS, WINDOW_MINUTES, callers_of

END = WINDOW_MINUTES * 60


def _mask(df: pd.DataFrame, service: str, t0: float, t1: float = END) -> pd.Series:
    return (df["service"] == service) & (df["t"] >= t0) & (df["t"] < t1)


def _ramp(df: pd.DataFrame, mask: pd.Series, t0: float, seconds: float) -> np.ndarray:
    return np.clip((df.loc[mask, "t"].to_numpy() - t0) / seconds, 0, 1)


def _log(logs, t, service, level, msg, key=False):
    logs.append({"t": int(t), "service": service, "level": level, "msg": msg, "_key": key})


def _every(rng, t0, t1, mean_gap):
    """Jittered event times between t0 and t1."""
    t = t0
    while t < t1:
        yield t
        t += max(5, rng.normal(mean_gap, mean_gap * 0.3))


# --- fault models: each returns the impact callers will feel -------------------------------

def _bad_deploy(df, logs, spec, rng):
    s, on, sev = spec.service, spec.onset_min * 60, spec.severity
    version = f"v2.{rng.integers(10, 40)}.{rng.integers(0, 9)}"
    _log(logs, on - 20, s, "INFO", f"Deployment {s}@{version} rolled out (3/3 pods ready)", key=True)
    m = _mask(df, s, on)
    df.loc[m, "error_rate"] += 0.12 * sev
    df.loc[m, "p95_latency_ms"] *= 1.3
    for t in _every(rng, on + 5, END, 25):
        _log(logs, t, s, "ERROR",
             f"Unhandled exception in POST /api/{s}/checkout: NullPointerException at CheckoutHandler.java:142 ({version})",
             key=True)
    return {"latency": 60 * sev, "error": 0.10 * sev}


def _db_pool_saturation(df, logs, spec, rng):
    s, on, sev = spec.service, spec.onset_min * 60, spec.severity
    m = _mask(df, s, on)
    r = _ramp(df, m, on, 120)
    base = BASELINE[s]["db_pool_used"] or 0.3
    df.loc[m, "db_pool_used"] = base + (1.0 - base) * r
    df.loc[m, "p95_latency_ms"] *= 1 + 12 * sev * r
    df.loc[m, "cpu"] += 0.2 * r
    for t in _every(rng, on + 60, END, 20):
        _log(logs, t, s, "ERROR",
             "remaining connection slots are reserved; timeout acquiring connection after 5000ms (pool 100/100 in use)",
             key=True)
    return {"latency": 1800 * sev, "error": 0.15 * sev}


def _downstream_timeout(df, logs, spec, rng):
    s, on, sev = spec.service, spec.onset_min * 60, spec.severity
    m = _mask(df, s, on)
    r = _ramp(df, m, on, 90)
    base = BASELINE[s]["p95_latency_ms"]
    df.loc[m, "p95_latency_ms"] = base + (5000 - base) * r * sev
    df.loc[m, "error_rate"] += 0.05 * sev * r
    for t in _every(rng, on + 45, END, 22):
        _log(logs, t, s, "ERROR", "handler timed out after 5000ms (worker pool 64/64 busy)", key=True)
    return {"latency": 3000 * sev, "error": 0.10 * sev}


def _memory_leak(df, logs, spec, rng):
    s, on, sev = spec.service, spec.onset_min * 60, spec.severity
    base = BASELINE[s]["mem"]
    ramp_s = min(max(300, 720 / sev), END - on - 60)
    t_cycle, first_oom = on, None
    while t_cycle < END:
        t_oom = t_cycle + ramp_s
        m = _mask(df, s, t_cycle, min(t_oom, END))
        df.loc[m, "mem"] = base + (0.97 - base) * _ramp(df, m, t_cycle, ramp_s)
        if t_oom < END:
            first_oom = first_oom or t_oom
            _log(logs, t_oom - 60, s, "WARN", "heap usage 93% of limit, GC unable to reclaim memory", key=True)
            _log(logs, t_oom, s, "ERROR", f"Container {s} OOMKilled (exit code 137), restarting", key=True)
            em = _mask(df, s, t_oom, t_oom + 60)
            df.loc[em, "error_rate"] += 0.2 * sev
        t_cycle = t_oom + 30
    # callers only feel it once the container starts getting killed
    return {"latency": 250 * sev, "error": 0.05 * sev, "start": first_oom or END - 60}


def _cache_stampede(df, logs, spec, rng):
    s, on, sev = spec.service, spec.onset_min * 60, spec.severity
    m = _mask(df, s, on)
    df.loc[m, "error_rate"] += 0.35 * sev  # miss/timeouts on GET
    df.loc[m, "cpu"] += 0.5 * sev
    _log(logs, on - 10, s, "INFO", "expired 182,344 keys (ttl=3600) in one sweep", key=True)
    for t in _every(rng, on + 15, END, 30):
        hit = int(rng.integers(8, 18))
        _log(logs, t, s, "WARN", f"cache miss storm: hit ratio dropped to {hit}% (baseline 94%)", key=True)
    # load shifts to the database a little later
    pm = _mask(df, "postgres", on + 60)
    df.loc[pm, "rps"] *= 1 + 0.8 * sev
    df.loc[pm, "cpu"] += 0.25 * sev
    return {"latency": 400 * sev, "error": 0.04 * sev}


FAULTS = {
    "bad_deploy": _bad_deploy,
    "db_pool_saturation": _db_pool_saturation,
    "downstream_timeout": _downstream_timeout,
    "memory_leak": _memory_leak,
    "cache_stampede": _cache_stampede,
}


def inject(metrics, logs, spec, rng) -> dict:
    """Apply the origin signal of `spec.fault` to `spec.service`; return the impact on callers."""
    return FAULTS[spec.fault](metrics, logs, spec, rng)


def propagate(metrics, logs, spec, rng, impact: dict) -> dict[str, int]:
    """Walk the dependency graph upstream, adding lagged, damped symptoms.

    Returns the symptom start time per affected upstream service.
    """
    starts = {spec.service: int(impact.get("start", spec.onset_min * 60))}
    frontier = [spec.service]
    hop = 0
    while frontier:
        hop += 1
        nxt = []
        for callee in frontier:
            for caller in callers_of(callee):
                if caller in starts:
                    continue
                lag = int(rng.integers(2, 7)) * STEP_SECONDS  # 30-90 s per hop
                start = starts[callee] + lag
                starts[caller] = start
                damp = 0.65 ** hop
                m = _mask(metrics, caller, start)
                r = _ramp(metrics, m, start, 60)
                metrics.loc[m, "p95_latency_ms"] += impact["latency"] * damp * r
                metrics.loc[m, "error_rate"] += impact["error"] * damp * r
                for t in _every(rng, start + 10, END, 40 + 20 * hop):
                    code = "504 Gateway Timeout" if impact["latency"] > 500 else "502 Bad Gateway"
                    _log(logs, t, caller, "ERROR", f"call to {callee} failed: {code}")
                nxt.append(caller)
        frontier = nxt
    return starts


def add_red_herrings(metrics, logs, spec, rng) -> None:
    """Inject misleading but unrelated signals listed in `spec.red_herrings`."""
    for rh in spec.red_herrings:
        t0, s = rh.at_min * 60, rh.service
        if rh.kind == "cpu_spike":
            m = _mask(metrics, s, t0, t0 + 180)
            metrics.loc[m, "cpu"] = 0.92 + rng.normal(0, 0.02, m.sum())
            _log(logs, t0, s, "INFO", "cron job nightly-report-export started")
            _log(logs, t0 + 180, s, "INFO", "cron job nightly-report-export finished in 178s")
        elif rh.kind == "noisy_warning":
            for t in _every(rng, t0, END, 240):
                _log(logs, t, s, "WARN", "config reload: deprecated key 'retry.backoff_ms' ignored")
        elif rh.kind == "unrelated_deploy":
            _log(logs, t0, s, "INFO", f"Deployment {s}@v1.{rng.integers(50, 90)}.0 rolled out (2/2 pods ready)")
        elif rh.kind == "gc_logs":
            for t in _every(rng, t0, END, 120):
                _log(logs, t, s, "WARN", f"GC pause {int(rng.integers(150, 260))}ms (G1 Evacuation Pause)")
        elif rh.kind == "disk_warning":
            for i, t in enumerate(_every(rng, t0, min(END, t0 + 900), 300)):
                _log(logs, t, s, "WARN", f"disk usage {82 + i}% on /var/log/app")
