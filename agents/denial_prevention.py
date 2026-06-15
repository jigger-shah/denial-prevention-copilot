"""
Denial Prevention Agent.

Synthesizes findings from all upstream agents into a single risk assessment:
  - Aggregates Finding lists from coding_validation, coverage_validation, and
    documentation_review.
  - Computes a claim-level denial risk score: HIGH if any HIGH-severity finding exists,
    MEDIUM if only MEDIUM findings, LOW if only LOW or no findings.
  - Applies denial pattern heuristics (e.g. known payer-specific denial triggers,
    CARC code patterns from historical denial data) to adjust severity or add
    supplementary findings.
  - Computes aggregate confidence across all findings; if below CONFIDENCE_THRESHOLD
    (set in config), sets escalation_required=True.
  - Orders findings by severity for display in the UI.

Does not call the LLM directly — synthesis is deterministic over structured
Finding objects. Returns a RiskAssessment(score, findings, escalation_required,
checks_run) Pydantic object.
"""
