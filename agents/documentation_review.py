"""
Documentation Review Agent.

LLM analysis of attached clinical note text (synthetic only in MVP):
  - E/M level support: does the documented medical decision making (MDM) or time
    support the billed E/M level (99202–99215)?
  - Diagnosis specificity: are ICD-10 codes coded to the highest specificity supported
    by the note (e.g. unspecified vs. laterality-specific)?
  - Required elements: are procedure-specific documentation requirements met
    (e.g. HCPCS G-code attestations, ABN requirements for potentially non-covered services)?
  - Supporting details: does the note contain sufficient clinical detail to survive a
    post-payment audit on the billed diagnoses?

Returns LOW-severity findings by default when no note is attached, noting that
risk assessment is code-only and documentation cannot be validated.

Primary sources: E/M guidelines, CMS documentation requirements (retrieved from
retrieval.vector_store), payer-specific documentation rules.
Returns a list of Finding objects with source="documentation_review".
"""
