"""Read-only tool layer: the only path from agents to incident data and the KB."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from sim.world import EDGES, METRICS
from triage.anomaly import anomalies

MAX_LOG_LINES = 50
MAX_METRIC_POINTS = 60
MAX_KB_CHARS = 700


class QueryLogsArgs(BaseModel):
    service: str | None = Field(None, description="service name, e.g. postgres")
    level: str | None = Field(None, description="INFO, WARN or ERROR")
    contains: str | None = Field(None, description="case-insensitive substring of the message")
    t0: int | None = Field(None, description="start, seconds since window start")
    t1: int | None = Field(None, description="end, seconds since window start")
    limit: int = Field(50, description="max lines, <= 50")


class GetMetricArgs(BaseModel):
    service: str
    metric: str = Field(description=", ".join(METRICS))
    t0: int | None = None
    t1: int | None = None


class ListAnomaliesArgs(BaseModel):
    service: str | None = None


class SearchKbArgs(BaseModel):
    query: str
    k: int = 5


class NoArgs(BaseModel):
    pass


class IncidentTools:
    """Tools bound to one incident folder. Never reads label.json or spec.json."""

    def __init__(self, incident_dir, retriever=None, tracer=None):
        d = Path(incident_dir)
        self.alert = json.loads((d / "alert.json").read_text())
        self.logs = [json.loads(l) for l in (d / "logs.jsonl").read_text().splitlines()]
        self.metrics = pd.read_parquet(d / "metrics.parquet")
        self.retriever = retriever
        self.tracer = tracer

    def _trace(self, agent, name, args, result):
        if self.tracer:
            text = json.dumps(result, default=str)
            self.tracer.emit(agent, "tool_call", tool=name, args=args, result_chars=len(text))
            self.tracer.saw(agent, text)
        return result

    def query_logs(self, service=None, level=None, contains=None, t0=None, t1=None, limit=MAX_LOG_LINES, _agent="tools"):
        limit = max(1, min(int(limit or MAX_LOG_LINES), MAX_LOG_LINES))
        out = [l for l in self.logs
               if (not service or l["service"] == service)
               and (not level or l["level"] == level.upper())
               and (not contains or contains.lower() in l["msg"].lower())
               and (t0 is None or l["t"] >= t0)
               and (t1 is None or l["t"] <= t1)]
        res = {"total_matches": len(out), "returned": min(len(out), limit), "lines": out[:limit]}
        return self._trace(_agent, "query_logs", dict(service=service, level=level, contains=contains, t0=t0, t1=t1), res)

    def get_metric(self, service, metric, t0=None, t1=None, _agent="tools"):
        if metric not in METRICS:
            return {"error": f"unknown metric {metric}; choose from {METRICS}"}
        sub = self.metrics[self.metrics["service"] == service].sort_values("t")
        if sub.empty:
            return {"error": f"unknown service {service}"}
        base = float(sub[metric].iloc[:20].mean())
        if t0 is not None:
            sub = sub[sub["t"] >= t0]
        if t1 is not None:
            sub = sub[sub["t"] <= t1]
        step = max(1, -(-len(sub) // MAX_METRIC_POINTS))
        pts = sub.iloc[::step]
        res = {
            "service": service, "metric": metric,
            "points": [[int(t), round(float(v), 4)] for t, v in zip(pts["t"], pts[metric])],
            "summary": {"min": round(float(sub[metric].min()), 4), "max": round(float(sub[metric].max()), 4),
                        "mean": round(float(sub[metric].mean()), 4), "baseline_mean": round(base, 4)},
        }
        return self._trace(_agent, "get_metric", dict(service=service, metric=metric, t0=t0, t1=t1), res)

    def list_anomalies(self, service=None, _agent="tools"):
        res = {"anomalies": anomalies(self.metrics, service)}
        return self._trace(_agent, "list_anomalies", dict(service=service), res)

    def search_kb(self, query, k=5, _agent="tools"):
        hits = self.retriever.search(query, k=min(int(k or 5), 5)) if self.retriever else []
        res = {"results": [{"chunk_id": h["chunk_id"], "doc_id": h["doc_id"], "score": h["score"],
                            "text": h["text"][:MAX_KB_CHARS]} for h in hits]}
        return self._trace(_agent, "search_kb", dict(query=query, k=k), res)

    def get_topology(self, _agent="tools"):
        res = {"edges": [{"caller": a, "callee": b} for a, b in EDGES]}
        return self._trace(_agent, "get_topology", {}, res)

    # --- LangChain adapters -----------------------------------------------------------------

    def as_langchain(self, names: list[str], agent: str) -> list[StructuredTool]:
        specs = {
            "query_logs": (QueryLogsArgs, lambda service=None, level=None, contains=None, t0=None, t1=None, limit=50:
                           self.query_logs(service, level, contains, t0, t1, limit, _agent=agent),
                           "Search incident logs. Filters: service, level (INFO/WARN/ERROR), contains (substring), "
                           "t0/t1 in seconds since window start, limit<=50. Lines carry citable ids like L000123."),
            "get_metric": (GetMetricArgs, lambda service, metric, t0=None, t1=None: self.get_metric(service, metric, t0, t1, _agent=agent),
                           f"Time series for one service metric (<=60 points) with min/max/mean/baseline_mean. "
                           f"Metrics: {', '.join(METRICS)}. t in seconds since window start."),
            "list_anomalies": (ListAnomaliesArgs, lambda service=None: self.list_anomalies(service, _agent=agent),
                               "Detected change points for every service/metric (or one service), sorted by start time."),
            "search_kb": (SearchKbArgs, lambda query, k=5: self.search_kb(query, k, _agent=agent),
                          "Hybrid search over runbooks and past postmortems. Results carry citable chunk_ids like rb-db-01#0."),
            "get_topology": (NoArgs, lambda: self.get_topology(_agent=agent),
                             "Service dependency edges (caller -> callee)."),
        }
        return [StructuredTool.from_function(func=specs[n][1], name=n, description=specs[n][2], args_schema=specs[n][0])
                for n in names]


ALL_TOOLS = ["query_logs", "get_metric", "list_anomalies", "search_kb", "get_topology"]
