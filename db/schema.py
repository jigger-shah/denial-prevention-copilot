"""
SQLite schema definitions and Pydantic data models.

Tables:
  claims        — one row per claim reviewed (claim_id, payer, npi, codes, dx,
                  modifiers, pos, units, submitted_at, status).
  findings      — one row per agent finding (finding_id, claim_id, source_agent,
                  severity, issue, recommended_fix, citation_doc_id,
                  citation_section, citation_effective_date, confidence, created_at).
  decisions     — one row per human action (decision_id, finding_id, claim_id,
                  action [accept|modify|override], modified_value, override_reason,
                  decided_by, decided_at). Append-only; no updates.
  audit_events  — catch-all timeline log (event_id, claim_id, event_type,
                  payload_json, created_at). Covers system events (rule failures,
                  low-confidence escalations) not captured in findings/decisions.

Pydantic models: ClaimIn, Finding, Decision, RiskAssessment, AuditEvent.
These are the shared data contracts between the rules layer, agents, and UI.
"""
