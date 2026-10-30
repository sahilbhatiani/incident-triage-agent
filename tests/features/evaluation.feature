Feature: Comparative evaluation of the two approaches
  As the experimenter
  I want deterministic checks plus an LLM judge over a replay matrix
  So that the final architecture choice is justified by measured results

  Background:
    Given a rendered incident with fault "db_pool_saturation" on "postgres"

  Scenario: Exact root-cause scoring
    Given a Diagnosis naming "db_pool_saturation" on "postgres"
    Then it is scored correct
    And a Diagnosis naming "db_pool_saturation" on "payments" is scored incorrect
    And a Diagnosis naming "unknown" is scored incorrect

  Scenario: The verifier flags a hallucinated log id
    Given a Diagnosis citing log "L999999" which does not exist
    When I verify its citations
    Then that citation is invalid and the valid-citation rate is below 1

  Scenario: The verifier flags a metric window with no anomaly
    Given a Diagnosis citing metric "redis.cpu@0-300"
    When I verify its citations
    Then that citation is invalid because the window has no anomaly

  Scenario: The verifier accepts real evidence
    Given a Diagnosis citing one of the label's key evidence log ids and "postgres.db_pool_used" over the fault window
    When I verify its citations
    Then the valid-citation rate is 1

  Scenario: The judge returns a structured verdict
    Given a scripted fake judge LLM
    When the judge scores a Diagnosis against the label
    Then the verdict has root_cause_match in correct/partial/incorrect, evidence_support from 1 to 5, and next_steps_safe true or false

  Scenario: The runner covers the matrix and caches results
    Given 2 incidents, approaches single and multi, and 2 seeds
    When I run the evaluation matrix with fake agents
    Then results.csv has 8 rows with columns incident, approach, seed, correct, citation_rate, tokens_in, tokens_out, cost_usd, latency_s, confidence
    And running it again executes no agents

  Scenario: Smoking-gun ablation removes the key evidence
    When I create the ablated copy of the incident
    Then none of the label's key_evidence_ids remain in its logs
    And the original incident is unchanged

  Scenario: The report summarises each approach
    Given a results.csv with rows for both approaches
    When I build the report
    Then it shows accuracy as n/N, mean citation rate, mean cost, p50 latency and calibration per approach and split
