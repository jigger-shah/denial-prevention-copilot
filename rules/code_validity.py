"""
Code validity lookups for ICD-10-CM, CPT, and HCPCS Level II.

Ingests annual ICD-10-CM code set and quarterly HCPCS Level II files from
data/reference/ and exposes lookup functions that verify:
  - ICD-10-CM: code exists in the current fiscal year's release, is a valid
    billable code (leaf node, not a header), and is not a placeholder-only code.
  - CPT: code is in the current year's CPT code set (from HCPCS crosswalk or
    bundled reference), is not deleted, and is appropriate for the reported
    place of service.
  - HCPCS Level II: code exists, is active (not terminated), and the termination
    date (if any) is after the date of service.

Diagnosis specificity is flagged when an unspecified code (typically ending in
.9 or having a more specific alternative) is used where a specific code exists.

Source: CMS ICD-10-CM (annual, October release); CMS HCPCS Level II (quarterly).
Refresh cadence: ICD-10 annual, HCPCS quarterly.
"""
