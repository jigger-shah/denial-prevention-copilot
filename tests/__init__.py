"""
Test suite for the Denial Prevention Copilot.

Test categories:
  test_rules/       — unit tests for deterministic lookups (ncci, mue, npi, code_validity).
                      These should run with no external API calls (fixture data only).
  test_agents/      — integration tests for each agent using synthetic claim fixtures
                      and mocked LLM responses.
  test_orchestrator — end-to-end orchestrator tests: given a synthetic claim, assert
                      the expected Finding types and severities are returned.
  test_retrieval/   — tests for chunking logic and vector store round-trips (local ChromaDB).
  test_db/          — tests for audit log write/read/export functions.

The golden set in data/synthetic/golden/ drives precision and recall metrics:
run `pytest tests/ -m golden` to evaluate against labelled claims.
"""
