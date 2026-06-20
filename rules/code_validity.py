"""
Code validity, diagnosis-to-procedure conflict, and modifier-presence checks.

Backed by hardcoded, curated rule tables (not file-backed — see each
citation_edition string). Covers: Z00.00 dx-procedure conflicts, and missing
modifier 25 (preventive context), 76/77 (repeat procedure), and 50
(bilateral procedure).
Production path: replace _load_dx_procedure_rules() with a loader that reads
ICD-10-CM reference data from data/reference/; replace the modifier rule
loaders with the NCCI Policy Manual modifier guidance.
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

# Procedure codes commonly repeated same-day where a repeat-procedure modifier
# (76/77) is expected if billed more than once (e.g. a second injection or a
# second arthrocentesis, not a duplicate-billing error).
_REPEATABLE_PROCEDURE_CODES = frozenset({"20610", "96372"})

# Procedure codes with a CMS bilateral surgery indicator of 1 (bilateral-
# eligible) where billing 2 units without modifier 50 (or both RT and LT) is
# a common, avoidable denial trigger.
_BILATERAL_ELIGIBLE_CODES = frozenset({"69210", "64483"})


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
            "citation_doc_id": "ICD10_Z00_PREVENTIVE_CONTEXT_SAMPLE",
            "citation_section": "ICD-10-CM Official Guidelines for Coding and Reporting, Section I.C.21.c — Factors Influencing Health Status (Z Codes)",
            "citation_edition": "ICD-10-CM Official Guidelines FY2026 (curated interpretive rule — not file-backed)",
            "citation_effective_date": "2025-10-01",
            "citation_excerpt": (
                "Z00.00: Encounter for general adult medical examination without abnormal findings. "
                "Problem-oriented E/M codes (99202–99215) are not appropriate as the primary code "
                "when the encounter is a routine preventive examination unless a separately "
                "identifiable service is documented."
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
            "citation_doc_id": "NCCI_MODIFIER_25_SAMPLE",
            "citation_section": "Chapter 1, Section D — Modifiers",
            "citation_edition": "NCCI Policy Manual for Medicare Services, Chapter 1 (curated interpretive rule — not file-backed)",
            "citation_effective_date": "2024-01-01",
            "citation_excerpt": (
                "Modifier 25 should be appended to an E/M service code to indicate that on the day "
                "of a procedure or service, the patient's condition required a significant, separately "
                "identifiable E/M service above and beyond the usual pre- and post-operative care. "
                "The E/M service must be documented separately and must meet the criteria for the "
                "level of service billed."
            ),
        },
    ]


def _load_repeat_modifier_rules() -> list[dict]:
    """Modifier 76/77 — repeat procedure or service by the same/another physician."""
    return [
        {
            "rule_id": "missing_modifier_76",
            "description": (
                "A repeatable procedure billed with more than one unit on the same "
                "date of service requires modifier 76 (repeat procedure by same "
                "physician) or 77 (by another physician) to distinguish a "
                "clinically separate repeat from duplicate billing."
            ),
            "required_modifiers": {"76", "77"},
            "trigger_cpt_codes": list(_REPEATABLE_PROCEDURE_CODES),
            "severity": "MEDIUM",
            "recommendation": (
                "Add modifier 76 or 77 if the procedure was clinically repeated on "
                "the same date, or correct the unit count if this is a single "
                "occurrence billed in error."
            ),
            "confidence": 0.65,
            "citation_source": "NCCI Policy Manual",
            "citation_doc_id": "NCCI_MODIFIER_76_SAMPLE",
            "citation_section": "Chapter 1, Section D — Modifiers",
            "citation_edition": "NCCI Policy Manual for Medicare Services, Chapter 1 (curated interpretive rule — not file-backed)",
            "citation_effective_date": "2024-01-01",
            "citation_excerpt": (
                "Modifier 76 indicates a repeat procedure or service by the same physician on the "
                "same day. Without a repeat-procedure modifier, multiple units of the same procedure "
                "code on a single date of service may be denied as a duplicate claim."
            ),
        },
    ]


def _load_bilateral_modifier_rules() -> list[dict]:
    """Modifier 50 — bilateral procedure, or the RT/LT modifier pair as an alternative."""
    return [
        {
            "rule_id": "missing_modifier_50",
            "description": (
                "A bilateral-eligible procedure billed with 2 units requires "
                "modifier 50 (bilateral procedure), or the RT and LT modifiers "
                "together, to indicate the procedure was performed on both sides."
            ),
            "required_modifiers": {"50"},
            "trigger_cpt_codes": list(_BILATERAL_ELIGIBLE_CODES),
            "severity": "MEDIUM",
            "recommendation": (
                "Add modifier 50 (or both RT and LT) if the procedure was performed "
                "bilaterally, or correct the unit count if it was performed on one side only."
            ),
            "confidence": 0.65,
            "citation_source": "NCCI Policy Manual",
            "citation_doc_id": "NCCI_MODIFIER_50_SAMPLE",
            "citation_section": "Chapter 1, Section D — Modifiers",
            "citation_edition": "NCCI Policy Manual for Medicare Services, Chapter 1 (curated interpretive rule — not file-backed)",
            "citation_effective_date": "2024-01-01",
            "citation_excerpt": (
                "Modifier 50 indicates a bilateral procedure performed during the same operative "
                "session. Procedures billed with 2 units but no bilateral or RT/LT modifier pair "
                "may be denied or down-coded as a duplicate of the same-side procedure."
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


def _check_repeat_modifier(claim: ClaimIn) -> list[Finding]:
    findings = []
    code_set = set(claim.cpt_codes)
    for rule in _load_repeat_modifier_rules():
        for cpt in code_set & set(rule["trigger_cpt_codes"]):
            units = claim.units.get(cpt, 1)
            if units <= 1:
                continue
            if set(rule["required_modifiers"]) & set(claim.modifiers):
                continue
            findings.append(Finding(
                rule=rule["rule_id"],
                severity=rule["severity"],
                issue=(
                    f"Possible missing modifier 76/77: {cpt} billed with {units} units "
                    f"and no repeat-procedure modifier"
                ),
                recommendation=rule["recommendation"],
                citation=_citation_from_rule(rule),
                confidence=rule["confidence"],
            ))
    return findings


def _check_bilateral_modifier(claim: ClaimIn) -> list[Finding]:
    findings = []
    code_set = set(claim.cpt_codes)
    for rule in _load_bilateral_modifier_rules():
        for cpt in code_set & set(rule["trigger_cpt_codes"]):
            units = claim.units.get(cpt, 1)
            if units < 2:
                continue
            has_50 = "50" in claim.modifiers
            has_rt_lt = "RT" in claim.modifiers and "LT" in claim.modifiers
            if has_50 or has_rt_lt:
                continue
            findings.append(Finding(
                rule=rule["rule_id"],
                severity=rule["severity"],
                issue=(
                    f"Possible missing modifier 50: {cpt} billed with {units} units "
                    f"and no bilateral or RT/LT modifier"
                ),
                recommendation=rule["recommendation"],
                citation=_citation_from_rule(rule),
                confidence=rule["confidence"],
            ))
    return findings


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def check_code_validity(claim: ClaimIn) -> list[Finding]:
    """
    Return Findings for:
      1. Diagnosis-to-procedure conflicts (dx does not support the billed E/M).
      2. Missing modifier situations:
         - modifier 25 (problem E/M in preventive-visit context)
         - modifier 76/77 (repeatable procedure billed >1 unit, no repeat modifier)
         - modifier 50 (bilateral-eligible procedure billed 2 units, no bilateral/RT+LT)
    """
    findings = []
    code_set = set(claim.cpt_codes)

    # --- Dx-to-procedure conflict checks ---
    # Intentionally exact-match, not prefix-match like missing_modifier_25 below.
    # TD-25 considered widening this to the full Z00 family (to match
    # missing_modifier_25's prefix match) but the golden evaluation set
    # (evaluation/golden_claims.json GOLD-005, GOLD-013) calibrates Z00.01 to
    # raise missing_modifier_25 only, NOT dx_procedure_conflict, while Z00.00
    # raises both (GOLD-006/007/014). That's a deliberate severity distinction
    # in the calibrated dataset, not an oversight — widening this check to
    # Z00.01 regresses two golden-set precision tests. TD-25 stays deferred.
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

    findings.extend(_check_repeat_modifier(claim))
    findings.extend(_check_bilateral_modifier(claim))

    return findings
