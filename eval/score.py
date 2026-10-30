"""Scoring: exact root-cause match, calibration and the smoking-gun ablation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np


def is_correct(diagnosis, label) -> bool:
    """Primary metric: exact match on (fault, service)."""
    return diagnosis.fault == label.fault and diagnosis.service == label.service


def expected_calibration_error(confidence, correct, bins: int = 5) -> float:
    conf, corr = np.asarray(confidence, float), np.asarray(correct, float)
    if len(conf) == 0:
        return float("nan")
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf >= lo) & ((conf < hi) | (hi == 1.0))
        if m.any():
            ece += m.mean() * abs(conf[m].mean() - corr[m].mean())
    return round(float(ece), 4)


def ablate_key_evidence(incident_dir, out_dir) -> Path:
    """Copy an incident with its key evidence log lines removed (metrics are kept)."""
    src = Path(incident_dir)
    dst = Path(out_dir) / f"{src.name}-ablated"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    keys = set(json.loads((src / "label.json").read_text())["key_evidence_ids"])
    lines = [l for l in (src / "logs.jsonl").read_text().splitlines() if json.loads(l)["id"] not in keys]
    (dst / "logs.jsonl").write_text("".join(l + "\n" for l in lines))
    alert = json.loads((dst / "alert.json").read_text())
    alert["alert_id"] += "-ablated"
    (dst / "alert.json").write_text(json.dumps(alert, indent=2))
    return dst
