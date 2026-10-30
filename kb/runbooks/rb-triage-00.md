---
doc_id: rb-triage-00
doc_type: runbook
service: gateway
fault_tags: []
---
# Runbook: General triage for gateway SLO alerts

## Principle
The gateway is the loudest service because every failure surfaces there, but it is rarely the root cause. Symptoms travel upstream from the failing dependency to its callers, arriving later and weaker at each hop.

## Procedure
1. Get the dependency topology: gateway calls orders; orders calls payments, inventory and redis; payments and inventory call postgres.
2. List anomalies for all services and sort by start time. The earliest sustained anomaly deep in the graph is the leading suspect.
3. Read ERROR and WARN logs on the suspect around its anomaly start.
4. Match the evidence pattern to a specific runbook: deploy regression, pool saturation, timeouts, memory leak or cache stampede.
5. Explicitly rule out red herrings: anomalies on services that are not upstream of the alerting path, or events with no impact on error_rate or latency.
