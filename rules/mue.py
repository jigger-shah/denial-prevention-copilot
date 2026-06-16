"""
NCCI MUE (Medically Unlikely Edit) rule check.

Compares reported units per CPT/HCPCS code against the CMS MUE table.
Returns a Finding for each code whose reported units exceed the MUE limit.

Severity is determined by the MAI (Medically Unlikely Edit Adjudication Indicator):
  MAI 1 → HIGH  (absolute per-line limit; cannot be bypassed)
  MAI 2 → MEDIUM (date-of-service edit; may be bypassable with documentation)
  MAI 3 → MEDIUM (date-of-service edit; clinical rationale may allow bypass)

Source: CMS NCCI Medically Unlikely Edits — Practitioner Services (quarterly).
"""

from rules.models import Citation, ClaimIn, Finding
from rules import mue_loader


def check_mue_limits(claim: ClaimIn) -> list[Finding]:
    """
    Return a Finding for each CPT/HCPCS code whose reported units exceed its MUE limit.

    Uses ClaimIn.units (a dict mapping cpt_code → reported_unit_count).
    Returns an empty list if units is empty or if no code exceeds its limit.
    """
    if not claim.units:
        return []

    findings: list[Finding] = []

    for code, reported_units in claim.units.items():
        entry = mue_loader.lookup_mue(code)
        if entry is None:
            continue

        mue_value = entry["mue_value"]
        if reported_units <= mue_value:
            continue

        mai = entry["mai"]
        mai_desc = mue_loader.MAI_DESCRIPTIONS.get(mai, f"MAI {mai}")
        severity: str = "HIGH" if mai == "1" else "MEDIUM"
        confidence: float = 0.97 if mai == "1" else 0.85

        excerpt = (
            f"CMS MUE Practitioner Services {mue_loader.MUE_VERSION} "
            f"(effective {mue_loader.MUE_EFFECTIVE_DATE}): "
            f"{code} has an MUE of {mue_value} unit(s). "
            f"{mai_desc}. "
            f"Reported units: {reported_units}. "
            f"Source: {entry['source_file']}."
        )

        findings.append(Finding(
            rule="mue_unit_limit",
            severity=severity,
            issue=(
                f"{code}: {reported_units} unit(s) reported — exceeds MUE limit of "
                f"{mue_value} ({mai_desc})"
            ),
            recommendation=(
                f"Reduce {code} to {mue_value} unit(s) per the CMS MUE table. "
                "For MAI 2/3 edits, retain supporting documentation in the medical record; "
                "additional units may be allowed with appropriate clinical rationale."
                if mai != "1" else
                f"Reduce {code} to {mue_value} unit(s). MAI 1 edits are absolute limits "
                "and cannot be bypassed by modifier or documentation."
            ),
            citation=Citation(
                source="CMS MUE",
                doc_id=mue_loader.MUE_DOC_ID,
                section=f"Practitioner Services MUE — {code}",
                edition=mue_loader.MUE_VERSION,
                effective_date=mue_loader.MUE_EFFECTIVE_DATE,
                excerpt=excerpt,
            ),
            confidence=confidence,
            source="rule_layer",
        ))

    return findings
