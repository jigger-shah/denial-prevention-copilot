"""
Code validity and diagnosis-to-procedure conflict checks.

Sprint 1: backed by hardcoded sample rule tables.
Production path: replace _load_dx_procedure_rules() with a loader that reads
ICD-10-CM reference data from data/reference/; replace _load_modifier_rules()
with the NCCI Policy Manual modifier guidance.
The public interface (check_code_validity) stays the same.
"""

from rules.models import Citation, ClaimIn, Finding


# ---------------------------------------------------------------------------
# Code sets — in production these are loaded from reference files
# ---------------------------------------------------------------------------

# Problem-oriented E/M codes (office/outpatient, established and new patients)
_PROBLEM_EM_CODES = frozenset({
    "99202", "99203", "99204", "99205",
    "99211", "99212", "99213", "99214", "99215",
})

# ICD-10 prefixes that signal a well/preventive-visit context
_PREVENTIVE_DX_PREFIXES = ("Z00",)


# ---------------------------------------------------------------------------
# Data sources — swap these functions for real reference data in production
# ---------------------------------------------------------------------------

def _load_dx_procedure_rules() -> list[dict]:
    """
    Returns diagnosis-to-procedure conflict rules.

    Each entry describes an ICD-10 code that is incompatible with a set of
    procedure codes, along with finding metadata and structured citation fields.
    """
    return [
        {
            "icd10": "Z00.00",
            "incompatible_cpt_codes": list(_PROBLEM_EM_CODES),
            "severity": "HIGH",
            "issue_template": (
                "{icd10} (routine exam, no abnormal findings) conflicts with "
                "problem-oriented E/M code {cpt}"
            ),
            "recommendation": (
                "Use the appropriate preventive visit code (e.g. 99395–99397), "
                "or add a specific problem diagnosis if the provider addressed a "
                "separate condition and the documentation supports it."
            ),
            "confidence": 0.90,
            # Citation fields
            "citation_source": "ICD-10-CM",
            "citation_doc_id": "ICD10CM-FY2026",
            "citation_section": "Z00.00 coding guidelines and usage notes",
            "citation_edition": "synthetic sample",
            "citation_effective_date": None,
            "citation_excerpt": (
                "Z00.00 — Encounter for general adult medical examination without "
                "abnormal findings. Use additional code to identify any "
                "abnormal findings."
            ),
        },
    ]


def _load_modifier_rules() -> list[dict]:
    """
    Returns modifier-presence rules.

    Each entry describes a condition under which a modifier is expected, and
    what finding to raise when it is absent.
    """
    return [
        {
            "rule_id": "missing_modifier_25",
            "description": (
                "A problem-oriented E/M billed alongside a preventive-visit "
                "diagnosis requires modifier 25 to establish that a separately "
                "identifiable E/M service occurred on the same date."
            ),
            "required_modifier": "25",
            "trigger_cpt_codes": list(_PROBLEM_EM_CODES),
            "trigger_dx_prefixes": list(_PREVENTIVE_DX_PREFIXES),
            "severity": "MEDIUM",
            "recommendation": (
                "Add modifier 25 to the E/M code only if a separately "
                "identifiable E/M service was documented beyond the preventive visit."
            ),
            "confidence": 0.75,
            # Citation fields
            "citation_source": "NCCI Policy Manual",
            "citation_doc_id": "NCCI-POLICY-MANUAL",
            "citation_section": "Chapter 1, Modifier 25 — Significant, Separately Identifiable E/M Service",
            "citation_edition": "synthetic sample",
            "citation_effective_date": None,
            "citation_excerpt": (
                "Modifier 25 should be appended to the E/M service code to indicate "
                "that on the day of a procedure or service, the patient's condition "
                "required a significant, separately identifiable E/M service."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_preventive_dx(claim: ClaimIn, prefixes: list) -> bool:
    return any(
        dx.startswith(prefix)
        for dx in claim.icd10_codes
        for prefix in prefixes
    )


def _citation_from_rule(rule: dict) -> Citation:
    """Build a Citation from the structured citation fields in a rule dict."""
    return Citation(
        source=rule["citation_source"],
        doc_id=rule["citation_doc_id"],
        section=rule["citation_section"],
        edition=rule["citation_edition"],
        effective_date=rule.get("citation_effective_date"),
        excerpt=rule.get("citation_excerpt"),
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def check_code_validity(claim: ClaimIn) -> list[Finding]:
    """
    Return Findings for:
      1. Diagnosis-to-procedure conflicts (dx does not support the billed E/M).
      2. Missing modifier situations (problem E/M in preventive-visit context
         without modifier 25).
    """
    findings = []
    code_set = set(claim.cpt_codes)

    # --- Dx-to-procedure conflict checks ---
    for rule in _load_dx_procedure_rules():
        if rule["icd10"] not in claim.icd10_codes:
            continue
        for cpt in rule["incompatible_cpt_codes"]:
            if cpt not in code_set:
                continue
            findings.append(Finding(
                rule="dx_procedure_conflict",
                severity=rule["severity"],
                issue=rule["issue_template"].format(icd10=rule["icd10"], cpt=cpt),
                recommendation=rule["recommendation"],
                citation=_citation_from_rule(rule),
                confidence=rule["confidence"],
            ))

    # --- Missing modifier checks ---
    for rule in _load_modifier_rules():
        has_trigger_cpt = bool(code_set & set(rule["trigger_cpt_codes"]))
        has_trigger_dx = _has_preventive_dx(claim, rule["trigger_dx_prefixes"])
        has_modifier = rule["required_modifier"] in claim.modifiers

        if has_trigger_cpt and has_trigger_dx and not has_modifier:
            trigger_cpt = next(
                c for c in claim.cpt_codes if c in set(rule["trigger_cpt_codes"])
            )
            findings.append(Finding(
                rule=rule["rule_id"],
                severity=rule["severity"],
                issue=(
                    f"Possible missing modifier {rule['required_modifier']}: "
                    f"{trigger_cpt} billed in preventive-visit context without "
                    f"modifier {rule['required_modifier']}"
                ),
                recommendation=rule["recommendation"],
                citation=_citation_from_rule(rule),
                confidence=rule["confidence"],
            ))

    return findings
