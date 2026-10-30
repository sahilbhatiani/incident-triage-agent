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
