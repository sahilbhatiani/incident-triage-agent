"""Deterministic citation verifier."""

from __future__ import annotations


def verify_citations(diagnosis, incident_dir, kb_chunk_ids) -> dict:
    """Return {valid, invalid, rate, details} for every citation in `diagnosis`."""
    raise NotImplementedError
