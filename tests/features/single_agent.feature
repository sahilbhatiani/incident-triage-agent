Feature: Approach A - single ReAct agent
  As the experimenter
  I want one agent with every tool to produce a structured diagnosis
  So that it is a fair baseline for the multi-agent approach

  Background:
    Given a rendered incident with fault "db_pool_saturation" on "postgres"
    And a scripted fake LLM

  Scenario: The agent returns a schema-valid diagnosis
    Given the fake LLM calls list_anomalies, then query_logs, then answers fault "db_pool_saturation" on "postgres"
    When the single agent triages the incident
    Then the result is a valid Diagnosis naming "db_pool_saturation" on "postgres"
    And the diagnosis has at least one citation

  Scenario: The agent has access to all five tools
    When I build the single agent
    Then it is bound to query_logs, get_metric, list_anomalies, search_kb and get_topology

  Scenario: The tool budget is enforced
    Given the fake LLM keeps requesting tool calls forever
    When the single agent triages the incident
    Then at most 15 tool calls are executed
    And the agent is forced to answer with a Diagnosis

  Scenario: Malformed final output is repaired or marked unknown
    Given the fake LLM answers with fault "disk_full", which is not in the taxonomy
    When the single agent triages the incident
    Then the result is a valid Diagnosis with fault "unknown"

  Scenario: Usage is recorded
    Given the fake LLM calls list_anomalies, then query_logs, then answers fault "db_pool_saturation" on "postgres"
    When the single agent triages the incident
    Then the trace summary reports tool calls, tokens and wall-clock time

  @live
  Scenario: Live smoke test against the real model
    Given the real agent model
    When the single agent triages the incident
    Then the result is a valid Diagnosis
