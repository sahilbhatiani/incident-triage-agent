Feature: Knowledge base ingestion and hybrid retrieval
  As a triage agent
  I want runbooks and past postmortems retrievable by exact error strings and by paraphrase
  So that I can ground my diagnosis in cited documentation

  Background:
    Given the knowledge base in "kb/" has been ingested with a deterministic fake embedder

  Scenario: Documents are chunked on headings with metadata
    Then every chunk has a chunk_id of the form "<doc_id>#<n>"
    And every chunk has doc_type, service and fault_tags metadata
    And no chunk exceeds 400 tokens

  Scenario: Every fault type has a runbook
    Then for each of the 5 fault types at least one runbook chunk is tagged with it

  Scenario: Exact error strings are found through BM25
    When I search the knowledge base for "timeout acquiring connection"
    Then a chunk tagged "db_pool_saturation" is in the top 3 results

  Scenario: Paraphrased symptoms are found through vectors
    When I search the knowledge base for "service keeps restarting and memory climbs steadily"
    Then a chunk tagged "memory_leak" is in the top 3 results

  Scenario: Reciprocal Rank Fusion combines both rankings
    Given a BM25 ranking "a,b,c" and a vector ranking "c,d,a"
    When I fuse them with RRF k=60
    Then the fused order starts with "a" and "c" ahead of "b" and "d"

  Scenario: Results are citable
    When I search the knowledge base for "redis hit rate dropped"
    Then I get at most 5 results
    And each result has chunk_id, doc_id, text and score
