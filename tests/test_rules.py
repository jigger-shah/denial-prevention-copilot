"""
Unit tests for the rules/ deterministic layer.

Tests use fixture data (small in-memory DataFrames or CSV snippets) — no live API
calls and no dependency on downloaded reference files. Each test asserts the exact
Finding fields returned by the rule function under test.

Key scenarios to cover:
  - NCCI: code pair with modifier indicator 0 → hard bundling finding.
  - NCCI: code pair with modifier indicator 1 → finding only when modifier absent.
  - NCCI: unknown pair → no finding.
  - MUE: units exceed MAI=1 limit → hard denial finding.
  - MUE: units exceed MAI=2 limit → medium finding with documentation note.
  - NPI: valid 10-digit NPI → no finding (mock API response).
  - NPI: deactivated NPI → high-severity finding.
  - code_validity: valid ICD-10 leaf code → no finding.
  - code_validity: header code (not billable) → finding.
  - code_validity: unspecified code with specific alternative → medium finding.
"""
