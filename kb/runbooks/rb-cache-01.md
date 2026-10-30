---
doc_id: rb-cache-01
doc_type: runbook
service: redis
fault_tags: [cache_stampede]
---
# Runbook: Cache stampede (thundering herd)

## Symptoms
- redis hit ratio collapses (WARN "cache miss storm: hit ratio dropped to 12%").
- A mass key expiry log line ("expired N keys (ttl=3600) in one sweep") precedes the storm.
- redis error_rate and cpu jump; postgres rps and cpu rise shortly after as misses fall through to the database.
- orders latency increases and gateway errors follow.

## Diagnosis
1. Check whether redis degraded before postgres. If so, the database load is a consequence, not the cause.
2. Look for synchronized TTL expiry or a cache flush.

## Safe next steps
- Enable request coalescing or stale-while-revalidate on hot keys.
- Add TTL jitter so keys do not expire together.
