---
doc_id: rb-deploy-01
doc_type: runbook
service: any
fault_tags: [bad_deploy]
---
# Runbook: Error spike after a deployment

## Symptoms
- error_rate on one service jumps as a step function, not a ramp.
- Stack traces such as NullPointerException or unhandled exception appear in that service's ERROR logs.
- Callers (orders, gateway) report 502 Bad Gateway shortly after.
- A "Deployment <service>@<version> rolled out" log line precedes the first error by under a minute.

## Diagnosis
1. List deployments in the 10 minutes before the alert. A deploy log line on the service whose errors started first is the strongest signal.
2. Confirm the exceptions reference the new version string.
3. Rule out unrelated deploys: a deployment on a service whose error_rate did not move is a red herring.

## Safe next steps
- Roll back the offending service to the previous version (operator action, requires approval).
- Freeze further deploys to that service until the regression is understood.
