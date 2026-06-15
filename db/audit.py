"""
Audit log read/write functions.

write_claim(claim: ClaimIn) -> claim_id
write_finding(finding: Finding) -> finding_id
write_decision(decision: Decision) -> decision_id
write_event(event: AuditEvent) -> event_id

get_claim_log(claim_id) -> dict with all findings, decisions, and events for a claim,
    ordered chronologically. Used by app/components/audit_view.py to render the
    decision trail.

export_claim_log(claim_id, path: str) -> None
    Writes the claim log to a CSV file at the given path for compliance export.

All write functions use INSERT, never UPDATE or DELETE, to preserve immutability.
The database file path is read from the DB_PATH environment variable (defaults to
db/copilot.sqlite).
"""
