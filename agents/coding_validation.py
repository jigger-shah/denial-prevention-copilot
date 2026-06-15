"""
Coding Validation Agent.

Performs deterministic lookups enhanced by rule interpretation:
  - NCCI PTP edit pairs: flag bundled procedure codes (modifier indicator 0 = no bypass).
  - MUE limits: flag units of service exceeding the medically unlikely edit per code.
  - Modifier logic: detect missing modifier 25 (separate E/M + procedure), modifier 59,
    and other common modifier-pair conflicts.
  - Code pair conflicts beyond NCCI (e.g. bilateral procedure rules, add-on codes billed
    without primary, unlisted codes billed with a codable equivalent).

Primary sources: rules.ncci (PTP file), rules.mue (MUE file), rules.code_validity.
Returns a list of Finding(source="coding_validation", severity, issue, fix, citation,
confidence) objects.
"""
