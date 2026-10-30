"""Deterministic citation verifier."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from triage.anomaly import anomalies

METRIC_REF = re.compile(r"^(?P<svc>[a-z]+)\.(?P<metric>[a-z0-9_]+)@(?P<t0>\d+)-(?P<t1>\d+)$")


def verify_citations(diagnosis, incident_dir, kb_chunks: dict[str, str]) -> dict:
    """Return {valid, invalid, total, rate, details, evidence_text} for every citation in `diagnosis`.

    log    -> the id exists in logs.jsonl
    metric -> the series exists and the window overlaps a detected anomaly on it
    doc    -> the chunk id exists in the knowledge base
    """
    d = Path(incident_dir)
    logs = {l["id"]: l for l in map(json.loads, (d / "logs.jsonl").read_text().splitlines())}
    metrics = pd.read_parquet(d / "metrics.parquet")
    anoms = anomalies(metrics)
    details, evidence = [], []
    for c in diagnosis.citations:
        ok, why = False, ""
        if c.kind == "log":
            ok = c.ref in logs
            why = "exists" if ok else "log id not found"
            if ok:
                l = logs[c.ref]
                evidence.append(f"{c.ref} {l['time']} {l['service']} {l['level']} {l['msg']}")
        elif c.kind == "metric":
            m = METRIC_REF.match(c.ref)
            if not m:
                why = "malformed metric ref"
            else:
                svc, metric, t0, t1 = m["svc"], m["metric"], int(m["t0"]), int(m["t1"])
                hits = [a for a in anoms if a["service"] == svc and a["metric"] == metric
                        and a["start"] <= t1 and a["end"] >= t0]
                ok = bool(hits)
                why = "overlaps anomaly" if ok else "window has no anomaly"
                if ok:
                    a = hits[0]
                    evidence.append(f"{c.ref}: {a['direction']} from t={a['start']} (peak z={a['peak_z']}, baseline {a['baseline_mean']})")
        elif c.kind == "doc":
            ok = c.ref in kb_chunks
            why = "exists" if ok else "chunk id not found"
            if ok:
                evidence.append(f"{c.ref}: {kb_chunks[c.ref][:300]}")
        details.append({"kind": c.kind, "ref": c.ref, "valid": ok, "reason": why})
    valid = sum(x["valid"] for x in details)
    total = len(details)
    return {"valid": valid, "invalid": total - valid, "total": total,
            "rate": round(valid / total, 4) if total else 0.0, "details": details,
            "evidence_text": "\n".join(evidence)}
