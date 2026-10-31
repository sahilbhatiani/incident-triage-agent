---
doc_id: rb-memory-01
doc_type: runbook
service: any
fault_tags: [memory_leak]
---
# Runbook: Memory leak and OOM restarts

## Symptoms
- mem on one service rises linearly for many minutes without falling back after GC.
- WARN "heap usage 93% of limit, GC unable to reclaim memory".
- ERROR "Container <service> OOMKilled (exit code 137), restarting", then mem drops and the ramp repeats.
- Callers see intermittent 502 errors clustered around each restart.

## Diagnosis
1. Plot mem for each service. A sawtooth (ramp, crash, reset) is the signature of a leak.
2. Errors upstream that coincide with restarts point back to the leaking service.
3. Disk usage warnings and GC pause logs on other services are common red herrings.

## Safe next steps
- Capture a heap dump before the next restart (operator approval required).
- Raise the memory limit temporarily and roll back recent changes to the leaking service.
