"""
Shared data models for the rule layer.

ClaimIn is the input contract for all rule functions.
Finding is the output contract — every rule returns a list of these.

Both are plain dataclasses (no external dependencies) so they can be
imported by rule modules, the rule engine, the UI, and tests without
pulling in the full agent/DB stack.
"""

from dataclasses import dataclass, field


@dataclass
class ClaimIn:
    claim_id: str
    payer: str
    npi: str
    cpt_codes: list
    icd10_codes: list
    modifiers: list
    place_of_service: str
    units: dict
    note_text: str = ""
    description: str = ""


@dataclass
class Finding:
    rule: str           # machine-readable rule identifier
    severity: str       # "HIGH" | "MEDIUM" | "LOW"
    issue: str          # short human-readable description of the problem
    recommendation: str # what the specialist should do
    citation: str       # source policy or edit table reference
    confidence: float   # 0.0–1.0; drives escalation threshold in future agent layer
