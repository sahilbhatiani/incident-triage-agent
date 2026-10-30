Feature: Approach B - coordinator with three specialists
  As the experimenter
  I want specialists to investigate in parallel and a coordinator to reconcile them
  So that I can test whether specialisation beats one generalist

  Background:
    Given a rendered incident with fault "db_pool_saturation" on "postgres"
    And a scripted fake LLM for each specialist and the coordinator

  Scenario: Specialists only get their own tools
    When I build the multi-agent graph
    Then the Logs specialist has query_logs and get_topology
    And the Metrics specialist has get_metric and list_anomalies
    And the Knowledge specialist has search_kb
    And the coordinator has no data tools

  Scenario: Specialists fan out in parallel
    When the multi-agent graph triages the incident
    Then all three specialists ran
    And their runs overlapped in time

  Scenario: Specialists hand off compressed findings
    When the multi-agent graph triages the incident
    Then each specialist returned at most 5 Findings
    And every Finding has a claim, a confidence and citations

  Scenario: Each specialist respects its budget
    Given every specialist's fake LLM keeps requesting tool calls forever
    When the multi-agent graph triages the incident
    Then no specialist executed more than 6 tool calls
    And the total across the graph is at most 15 plus the follow-up allowance

  Scenario: The coordinator reconciles findings into a diagnosis
    When the multi-agent graph triages the incident
    Then the result is a valid Diagnosis
    And its citations are a subset of the citations in the specialists' findings

  Scenario: Conflicting findings trigger at most one follow-up
    Given the Logs and Metrics specialists blame different services
    When the multi-agent graph triages the incident
    Then the coordinator issued exactly 1 follow-up to one specialist
    And no second follow-up round happened

  Scenario: Handoff loss is measurable
    When the multi-agent graph triages the incident
    Then the trace records which evidence ids specialists saw and which they handed off

  @live
  Scenario: Live smoke test against the real model
    Given the real agent model
    When the multi-agent graph triages the incident
    Then the result is a valid Diagnosis
