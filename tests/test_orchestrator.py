"""
End-to-end orchestrator tests using synthetic claim fixtures.

Uses the worked example from the PRD (99214 + 80053 + 80048 + 36415, dx Z00.00,
Medicare) as the canonical test case: asserts that the orchestrator returns
at least two HIGH-severity findings (NCCI bundling of 80048 into 80053, and
diagnosis-to-E/M mismatch) and one MEDIUM finding (modifier 25 scenario).

Additional fixture claims exercise:
  - Clean claim (no findings expected) → "no denial risks identified" result.
  - Hard NPI failure → short-circuit before agent pass.
  - Low aggregate confidence → escalation_required=True in RiskAssessment.

LLM calls are mocked via pytest fixtures to keep tests fast and deterministic.
"""
