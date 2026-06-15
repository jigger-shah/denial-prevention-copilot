"""
NCCI PTP (Procedure-to-Procedure) edit table lookups.

Ingests the CMS quarterly NCCI PTP edit CSV files (one for physician/practitioner
services, one for outpatient hospital services) from data/reference/ and exposes
a lookup function that, given a pair of CPT/HCPCS codes, returns:
  - Whether a PTP edit exists for the pair.
  - Which code is the column 1 (comprehensive) and column 2 (component) code.
  - The modifier indicator (0 = no modifier bypass allowed, 1 = bypass with
    appropriate modifier, 9 = not applicable).

NCCI files are versioned by quarter (e.g. "2025Q4") so citations can name the
exact edition. The module raises DataExpiredError if the loaded file is more than
one quarter old.

Source: CMS NCCI edit tables (https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits).
Refresh cadence: quarterly.
"""
