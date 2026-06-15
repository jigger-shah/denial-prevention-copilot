"""
Coverage Validation Agent.

Retrieval-grounded reasoning for medical necessity and coverage policy:
  - Query retrieval.vector_store with the claim's diagnosis + procedure combination
    to retrieve relevant NCD/LCD sections.
  - Use the Claude API (structured tool use) to reason over retrieved text: does the
    documented diagnosis support the procedure under the governing LCD/NCD?
  - Flag diagnosis-to-procedure mismatches, missing required diagnoses for coverage,
    and procedure limitations (frequency, setting, beneficiary age).

Every finding must carry a citation (document_id, section, effective_date) sourced
from the retrieved text. Findings without a verifiable citation are suppressed.

Primary sources: CMS Coverage API via retrieval.vector_store (NCD/LCD chunks).
Returns a list of Finding objects with source="coverage_validation".
"""
