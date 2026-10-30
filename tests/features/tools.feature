Feature: Read-only tool layer with a label firewall
  As the system owner
  I want agents to see incident data only through capped, read-only tools
  So that the comparison is fair and the ground truth can never leak

  Background:
    Given a rendered incident with fault "db_pool_saturation" on "postgres"
    And tools bound to that incident

  Scenario: Querying logs returns citable lines within the cap
    When I call query_logs with service "postgres" and level "ERROR"
    Then I get at most 50 lines
    And every line has an id, timestamp, service, level and message

  Scenario: Log filters narrow the result
    When I call query_logs with contains "connection" between minute 15 and minute 40
    Then every returned line contains "connection" and falls inside that window

  Scenario: Metrics are downsampled with summary stats
    When I call get_metric for "postgres" "db_pool_used"
    Then I get at most 60 points
    And a summary with min, max, mean and baseline_mean

  Scenario: Anomaly listing finds the injected change point
    When I call list_anomalies
    Then the results include "postgres" "db_pool_used" with a start near minute 20

  Scenario: Topology is available
    When I call get_topology
    Then I get the 6 dependency edges

  Scenario: The label never leaks through any tool
    When I call every tool with broad arguments
    Then no output contains the strings "label", "db_pool_saturation" or "key_evidence"

  Scenario: Tools cannot write
    When I call every tool
    Then the incident folder is unchanged on disk

  Scenario: Every tool call is traced
    Given a tracer attached to the tools
    When I call query_logs and get_metric
    Then the tracer recorded 2 tool_call events with their arguments
