"""
Rule engine — the single entry point the UI calls.

Orchestrates all deterministic rule modules, aggregates their findings,
and returns a sorted list plus an overall risk level.  No LLM involvement.

When the agent layer is added in a later sprint, the orchestrator will call
this module first (deterministic checks) before dispatching agents.
"""

from rules.models import ClaimIn, Finding
from rules import ncci, code_validity


_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def load_claim(claim_dict: dict) -> ClaimIn:
    """Construct a ClaimIn from a raw dict (e.g. parsed from JSON)."""
    return ClaimIn(
        claim_id=claim_dict["claim_id"],
        payer=claim_dict["payer"],
        npi=claim_dict["npi"],
        cpt_codes=claim_dict["cpt_codes"],
        icd10_codes=claim_dict["icd10_codes"],
        modifiers=claim_dict.get("modifiers", []),
        place_of_service=claim_dict["place_of_service"],
        units=claim_dict.get("units", {}),
        note_text=claim_dict.get("note_text", ""),
        description=claim_dict.get("description", ""),
    )


def review_claim(claim: ClaimIn) -> list[Finding]:
    """
    Run all rule checks against a claim and return findings sorted HIGH → MEDIUM → LOW.

    Adding a new rule module: import it above and append its checker call here.
    The interface contract is: checker(claim: ClaimIn) -> list[Finding].
    """
    findings: list[Finding] = []
    findings.extend(ncci.check_ncci_pairs(claim))
    findings.extend(code_validity.check_code_validity(claim))
    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 9))
    return findings


def overall_risk(findings: list[Finding]) -> str:
    """
    Derive the claim-level risk label from the highest-severity finding.
    Returns "HIGH", "MEDIUM", "LOW", or "CLEAN" (no findings).
    """
    if not findings:
        return "CLEAN"
    severities = {f.severity for f in findings}
    if "HIGH" in severities:
        return "HIGH"
    if "MEDIUM" in severities:
        return "MEDIUM"
    return "LOW"
