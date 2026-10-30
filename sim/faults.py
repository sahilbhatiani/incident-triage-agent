"""Fault library and upstream propagation of symptoms."""

from __future__ import annotations


def inject(metrics, logs, spec, rng):
    """Apply the origin signal of `spec.fault` to `spec.service`."""
    raise NotImplementedError


def propagate(metrics, logs, spec, rng):
    """Walk the dependency graph upstream, adding lagged, damped symptoms."""
    raise NotImplementedError


def add_red_herrings(metrics, logs, spec, rng):
    """Inject misleading but unrelated signals listed in `spec.red_herrings`."""
    raise NotImplementedError
