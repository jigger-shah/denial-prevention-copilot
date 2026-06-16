"""
Rule engine — the single entry point the UI calls.

Orchestrates all deterministic rule modules, aggregates their findings,
and returns a sorted list plus an overall risk level.  No LLM involvement.

When the agent layer is added in a later sprint, the orchestrator will call
this module first (deterministic checks) before dispatching agents.
"""

import hashlib

from rules.models import ClaimIn, Finding
from rules import ncci, mue, code_validity, npi


_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _make_finding_id(claim_id: str, rule: str, issue: str) -> str:
    """
    Deterministic, stable finding identifier derived from claim + rule + issue.

    SHA-256 is used (not Python's built-in hash()) so the ID is identical
    across processes and interpreter restarts — a requirement for the audit
    log's foreign key from decisions → findings.
    """
    key = f"{claim_id}:{rule}:{issue}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def load_claim(claim_dict: dict) -> ClaimIn:
    """Construct a ClaimIn from a raw dict (e.g. parsed from JSON).

    Accepts both sample-claim format (payer key) and manual-claim format
    (payer_name key). npi and place_of_service default to "" when absent
    so manual claims that omit those optional fields still parse cleanly.
    """
    return ClaimIn(
        claim_id=claim_dict["claim_id"],
        payer=claim_dict.get("payer") or claim_dict.get("payer_name", ""),
        npi=claim_dict.get("npi", ""),
        cpt_codes=claim_dict["cpt_codes"],
        icd10_codes=claim_dict["icd10_codes"],
        modifiers=claim_dict.get("modifiers", []),
        place_of_service=claim_dict.get("place_of_service", ""),
        units=claim_dict.get("units", {}),
        note_text=claim_dict.get("note_text", ""),
        description=claim_dict.get("description", ""),
    )


def review_claim(claim: ClaimIn) -> list[Finding]:
    """
    Run all rule checks against a claim and return findings sorted HIGH → MEDIUM → LOW.

    Adding a new rule module: import it above and append its checker call here.
    The interface contract is: checker(claim: ClaimIn) -> list[Finding].

    finding_id is stamped here (not in rule modules) because it requires claim_id,
    which rule modules do not need to know about.
    """
    findings: list[Finding] = []

    # NPI runs first. A HIGH finding (invalid format or Luhn failure) short-circuits
    # so downstream coding checks do not run — invalid provider identity makes
    # code-level checks unreliable and would produce misleading findings.
    npi_findings = npi.check_npi(claim)
    if any(f.severity == "HIGH" for f in npi_findings):
        for f in npi_findings:
            f.finding_id = _make_finding_id(claim.claim_id, f.rule, f.issue)
        return npi_findings

    findings.extend(npi_findings)  # MEDIUM NPI findings (not found) still included
    findings.extend(ncci.check_ncci_pairs(claim))
    findings.extend(mue.check_mue_limits(claim))
    findings.extend(code_validity.check_code_validity(claim))
    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 9))

    for finding in findings:
        finding.finding_id = _make_finding_id(claim.claim_id, finding.rule, finding.issue)

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
