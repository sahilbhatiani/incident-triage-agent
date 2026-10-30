"""Read-only tool layer: the only path from agents to incident data and the KB."""

from __future__ import annotations

MAX_LOG_LINES = 50
MAX_METRIC_POINTS = 60


class IncidentTools:
    """Tools bound to one incident folder. Never reads label.json."""

    def __init__(self, incident_dir, retriever):
        raise NotImplementedError

    def query_logs(self, service=None, level=None, contains=None, t0=None, t1=None, limit=MAX_LOG_LINES):
        raise NotImplementedError

    def get_metric(self, service, metric, t0=None, t1=None):
        raise NotImplementedError

    def list_anomalies(self, service=None):
        raise NotImplementedError

    def search_kb(self, query, k=5):
        raise NotImplementedError

    def get_topology(self):
        raise NotImplementedError
