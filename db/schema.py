"""
SQLite schema reference for the Denial Prevention Copilot audit database.

Implemented table: audit_decisions (see db/audit_repository.py for DDL).

audit_decisions columns
-----------------------
id               INTEGER  PK AUTOINCREMENT
timestamp        TEXT     ISO-8601 UTC insert time
claim_id         TEXT     claim being reviewed
finding_id       TEXT     12-char SHA-256 hex from rule_engine._make_finding_id()
source           TEXT     "rule_layer" | "agent_layer"
severity         TEXT     "HIGH" | "MEDIUM" | "LOW"
issue            TEXT     human-readable finding description
recommendation   TEXT     suggested corrective action
citation_source  TEXT     human label e.g. "NCCI PTP"
citation_doc_id  TEXT     stable document identifier e.g. "NCCI-PTP-SYNTHETIC"
citation_section TEXT     table, chapter, or policy section cited
citation_edition TEXT     version label e.g. "FY2026" or "synthetic sample"
confidence       REAL     0.0–1.0 rule engine confidence score
user_decision    TEXT     "accepted" | "overridden"
override_reason  TEXT     required non-empty when user_decision == "overridden"
reviewer_name    TEXT     human reviewer identifier
model_version    TEXT     rule/model version that produced the finding
prompt_version   TEXT     prompt version ("n/a" for pure rule layer)

Design notes
------------
- Append-only: no UPDATE or DELETE is ever issued.
- finding_id is deterministic (SHA-256) so decisions can be correlated
  with findings across sessions without a findings table.
- Governance: citation_source + citation_doc_id must be non-empty before
  a decision is persisted (enforced by AuditRepository.save_decision).
"""
