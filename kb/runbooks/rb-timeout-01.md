---
doc_id: rb-timeout-01
doc_type: runbook
service: any
fault_tags: [downstream_timeout]
---
# Runbook: Downstream dependency timeouts

## Symptoms
- p95_latency_ms on one service ramps up to the 5000ms client timeout.
- That service logs "handler timed out after 5000ms" and "worker pool 64/64 busy".
- Callers log "call to <service> failed: 504 Gateway Timeout" and retry, amplifying load.

## Diagnosis
1. Find the deepest service in the call chain whose latency rose first. Callers degrade later and less.
2. Distinguish from database saturation: if postgres db_pool_used is normal, the slow service itself is the cause.
3. Retry storms upstream are a symptom, not the cause.

## Safe next steps
- Enable circuit breakers on callers of the slow service.
- Scale out the slow service's worker pool if CPU allows.
