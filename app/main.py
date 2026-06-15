"""
Entry point for the Streamlit application.

Renders three views:
  1. Claim Intake — manual form entry (payer, NPI, CPT/HCPCS, ICD-10, modifiers,
     place of service, units) plus CSV upload for batch review.
  2. Findings Panel — denial risk score, per-finding severity / fix / citation cards
     with expandable source excerpts; accept / modify / override controls.
  3. Audit Log — per-claim decision trail exportable to CSV.

Calls agents.orchestrator.review_claim() and writes results to db.audit.
"""
