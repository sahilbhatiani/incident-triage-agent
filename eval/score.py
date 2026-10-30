"""Scoring: exact root-cause match, calibration and the smoking-gun ablation."""

from __future__ import annotations


def is_correct(diagnosis, label) -> bool:
    raise NotImplementedError


def ablate_key_evidence(incident_dir, out_dir):
    """Copy an incident with its key evidence log lines removed."""
    raise NotImplementedError
