"""Pydantic data contracts shared by the simulator, agents and evaluator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FaultType = Literal[
    "bad_deploy",
    "db_pool_saturation",
    "downstream_timeout",
    "memory_leak",
    "cache_stampede",
]
ServiceName = Literal["gateway", "orders", "payments", "inventory", "redis", "postgres"]


class RedHerring(BaseModel):
    kind: Literal["cpu_spike", "noisy_warning", "unrelated_deploy", "gc_logs", "disk_warning"]
    service: ServiceName
    at_min: int = Field(ge=0, le=59)


class ChaosSpec(BaseModel):
    incident_id: str
    fault: FaultType
    service: ServiceName
    onset_min: int = Field(ge=5, le=50)
    severity: float = Field(ge=0.1, le=1.0)
    red_herrings: list[RedHerring] = []
    noise: float = Field(default=0.1, ge=0.0, le=1.0)
    seed: int = 0


class Label(BaseModel):
    fault: FaultType
    service: ServiceName
    onset_ts: int
    key_evidence_ids: list[str]


class Citation(BaseModel):
    kind: Literal["log", "metric", "doc"]
    ref: str  # "L000123" | "postgres.db_pool_used@600-900" | "rb-db-03#2"


class Finding(BaseModel):
    agent: str
    claim: str
    citations: list[Citation] = []
    confidence: float = Field(ge=0.0, le=1.0)


class Diagnosis(BaseModel):
    fault: FaultType | Literal["unknown"]
    service: ServiceName | Literal["unknown"]
    explanation: str
    citations: list[Citation] = []
    confidence: float = Field(ge=0.0, le=1.0)
    operator_checks: list[str] = []
    safe_next_steps: list[str] = []


# --- agent submission contracts ----------------------------------------------------------------

FAULTS = ["bad_deploy", "db_pool_saturation", "downstream_timeout", "memory_leak", "cache_stampede"]
SERVICES = ["gateway", "orders", "payments", "inventory", "redis", "postgres"]


class FindingIn(BaseModel):
    claim: str
    citations: list[Citation] = []
    confidence: float = Field(ge=0.0, le=1.0)


class FindingsSubmission(BaseModel):
    findings: list[FindingIn] = Field(max_length=5)


class FollowupRequest(BaseModel):
    specialist: Literal["logs", "metrics", "knowledge"]
    question: str


def _citations(raw) -> list[Citation]:
    out = []
    for c in raw or []:
        try:
            out.append(Citation.model_validate(c))
        except Exception:
            continue
    return out


def coerce_diagnosis(args: dict | None) -> Diagnosis:
    """Validate a submitted diagnosis; out-of-taxonomy values become "unknown" instead of failing."""
    if not args:
        return Diagnosis(fault="unknown", service="unknown", explanation="no diagnosis submitted", confidence=0.0)
    a = dict(args)
    a["fault"] = a.get("fault") if a.get("fault") in FAULTS else "unknown"
    a["service"] = a.get("service") if a.get("service") in SERVICES else "unknown"
    a["citations"] = _citations(a.get("citations"))
    try:
        a["confidence"] = min(1.0, max(0.0, float(a.get("confidence", 0.0))))
    except (TypeError, ValueError):
        a["confidence"] = 0.0
    a.setdefault("explanation", "")
    a["operator_checks"] = [str(x) for x in a.get("operator_checks") or []]
    a["safe_next_steps"] = [str(x) for x in a.get("safe_next_steps") or []]
    return Diagnosis.model_validate(a)


def coerce_findings(args: dict | None, agent: str, limit: int = 5) -> list[Finding]:
    out = []
    for f in (args or {}).get("findings", [])[:limit]:
        try:
            out.append(Finding(agent=agent, claim=str(f["claim"]), citations=_citations(f.get("citations")),
                               confidence=min(1.0, max(0.0, float(f.get("confidence", 0.5))))))
        except Exception:
            continue
    return out
