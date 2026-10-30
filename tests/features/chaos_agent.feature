Feature: Red-team Chaos Agent designs adversarial incidents
  As the experimenter
  I want an LLM adversary to design hard incidents
  So that the approaches are tested beyond hand-written cases without fabricating data

  Scenario: The red team only emits valid ChaosSpecs
    Given a scripted fake LLM that proposes 3 specs
    When the red team proposes specs from past failures
    Then I get 3 valid ChaosSpec objects

  Scenario: Invalid proposals are rejected, not repaired with invented data
    Given a scripted fake LLM that proposes a spec with fault "alien_invasion"
    When the red team proposes specs from past failures
    Then that proposal is dropped and reported as rejected

  Scenario: The red team's incidents get labels from the simulator
    Given a valid ChaosSpec proposed by the red team
    When I render it into the adversarial split
    Then its label equals the spec's fault and service
    And rendering it again gives an identical incident

  Scenario: Proposals are steered by past failures
    Given past failures where approaches confused "payments" with "postgres"
    When the red team proposes specs from past failures
    Then the prompt sent to the LLM contains those failure summaries
