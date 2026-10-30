---
doc_id: rb-db-01
doc_type: runbook
service: postgres
fault_tags: [db_pool_saturation]
---
# Runbook: Database connection pool saturation

## Symptoms
- postgres db_pool_used climbs to 100% (pool 100/100 in use).
- ERROR logs: "remaining connection slots are reserved", "timeout acquiring connection after 5000ms".
- p95 latency on postgres rises sharply, followed by payments and inventory latency, then 504 Gateway Timeout on orders and gateway.

## Diagnosis
1. Check db_pool_used on postgres. If it saturated before any caller degraded, the database is the root cause.
2. Look for long-running queries or connection leaks in callers.
3. A CPU spike on an unrelated service at the same time (for example a cron job) is usually a red herring.

## Safe next steps
- Identify and terminate idle-in-transaction sessions (operator approval required).
- Temporarily lower caller concurrency or enable request shedding at the gateway.
- Do not restart postgres during peak traffic.
