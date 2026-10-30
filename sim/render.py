"""Render a ChaosSpec into an incident folder: alert, logs, metrics and a sealed label."""

from __future__ import annotations

from pathlib import Path


def render(spec, out_dir: Path) -> Path:
    """Deterministically build the incident for `spec` and write it to `out_dir/<id>/`."""
    raise NotImplementedError


def generate_standard_set(out_dir: Path) -> list[Path]:
    """Render the standard split: every fault type x 3 variants."""
    raise NotImplementedError
