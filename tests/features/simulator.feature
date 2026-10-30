Feature: Chaos Engine renders reproducible incidents with ground truth by construction
  As the evaluator
  I want incidents generated from a ChaosSpec by a deterministic simulator
  So that every label is a fact about what was injected, not an opinion

  Background:
    Given the service topology gateway -> orders -> payments -> postgres, orders -> inventory -> postgres, orders -> redis

  Scenario: Same spec and seed produce an identical incident
    Given a ChaosSpec with fault "db_pool_saturation" on "postgres" at minute 20 with seed 7
    When I render it twice into separate folders
    Then the logs, metrics and alert files are byte-identical

  Scenario: Different seeds change the noise but not the label
    Given a ChaosSpec with fault "memory_leak" on "payments" at minute 15 with seed 1
    When I render it with seed 1 and again with seed 2
    Then the metrics differ
    And both labels name fault "memory_leak" on service "payments"

  Scenario Outline: Each fault produces its origin signal on the faulty service
    Given a ChaosSpec with fault "<fault>" on "<service>" at minute 20 with seed 3
    When I render it
    Then the metric "<metric>" on "<service>" shifts after minute 20 compared with its baseline
    And at least one log line on "<service>" contains "<log_text>"

    Examples:
      | fault              | service   | metric         | log_text                       |
      | bad_deploy         | orders    | error_rate     | deploy                         |
      | db_pool_saturation | postgres  | db_pool_used   | timeout acquiring connection   |
      | downstream_timeout | inventory | p95_latency_ms | timed out                      |
      | memory_leak        | payments  | mem            | OOMKilled                      |
      | cache_stampede     | redis     | error_rate     | cache miss                     |

  Scenario: Symptoms propagate upstream with lag and damping
    Given a ChaosSpec with fault "db_pool_saturation" on "postgres" at minute 20 with seed 3
    When I render it
    Then "payments" shows elevated p95_latency_ms starting later than "postgres" shows its anomaly
    And "gateway" shows elevated error_rate starting later than "payments"
    And services not upstream of "postgres", such as "redis", stay within baseline

  Scenario: Red herrings appear but are not the root cause
    Given a ChaosSpec with fault "db_pool_saturation" on "postgres" and a "cpu_spike" red herring on "inventory" at minute 10
    When I render it
    Then "inventory" cpu is anomalous around minute 10
    And the label still names "postgres" as the root-cause service

  Scenario: The label is sealed away from agent-visible files
    Given a ChaosSpec with fault "bad_deploy" on "orders" at minute 25 with seed 4
    When I render it
    Then the incident folder contains alert.json, logs.jsonl, metrics.parquet and label.json
    And no agent-visible file contains the string "bad_deploy"
    And label.json lists key_evidence_ids that exist in logs.jsonl

  Scenario: Log lines carry stable citable ids
    Given a rendered incident
    Then every log line has an id matching "L\d{6}" and ids are unique

  Scenario: The standard set covers every fault
    When I generate the standard set
    Then there are 15 incidents, 3 per fault type
