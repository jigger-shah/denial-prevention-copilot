"""
HCPCS Level II code recognition check (TD-06).

Deliberately small in scope: this is not a full HCPCS Level II platform.
CPT codes (5 numeric digits) are out of scope here — they are covered by
rules/code_validity.py and rules/icd10.py. This module only looks at codes
in ClaimIn.cpt_codes that match the HCPCS Level II format (one letter A-V
followed by 4 digits) and checks them against a small curated set of
common, high-value codes (preventive G-codes, drug J-codes, supply/DME
A-/E-codes). A HCPCS-format code that is not in the curated set is flagged
as MEDIUM ("unrecognized", not "invalid") — the curated set is intentionally
narrow, so absence is a signal to verify manually, not a denial certainty.

Production path: replace _KNOWN_HCPCS with a file-backed loader (mirroring
rules/icd10_loader.py) reading the quarterly CMS HCPCS Level II file, if the
curated set proves too narrow for real use. The public interface
(check_hcpcs_validity) is unchanged.
"""

import re

from rules.models import Citation, ClaimIn, Finding

_HCPCS_FORMAT = re.compile(r"^[A-V]\d{4}$")

# Curated set of common, high-value HCPCS Level II codes. Not exhaustive —
# see module docstring.
_KNOWN_HCPCS: dict[str, str] = {
    "G0438": "Annual wellness visit, initial",
    "G0439": "Annual wellness visit, subsequent",
    "G0402": "Initial preventive physical examination (Welcome to Medicare)",
    "G0468": "Federally qualified health center visit, IPPE or AWV",
    "G0008": "Administration of influenza virus vaccine",
    "G0009": "Administration of pneumococcal vaccine",
    "J3490": "Unclassified drug",
    "J1100": "Injection, dexamethasone sodium phosphate, 1 mg",
    "J0696": "Injection, ceftriaxone sodium, per 250 mg",
    "J7050": "Infusion, normal saline solution, 250 cc",
    "A4253": "Blood glucose test strips, per 50 strips",
    "A4206": "Syringe with needle, sterile, 1 cc or less",
    "A0425": "Ground mileage, per statute mile",
    "E0114": "Crutches, underarm, other than wood",
    "E0143": "Walker, folding, wheeled, adjustable or fixed height",
    "Q4001": "Cast supplies, short arm cast, adult",
}

_CITATION_DOC_ID = "HCPCS_LEVEL_II_CURATED_SET_SAMPLE"
_CITATION_EDITION = "Curated common-code reference (not file-backed — see TD-06)"


def _citation(code: str, recognized: bool) -> Citation:
    if recognized:
        excerpt = f"{code}: {_KNOWN_HCPCS[code]}."
    else:
        excerpt = (
            f"{code} matches the HCPCS Level II code format (one letter followed by "
            "4 digits) but is not in the curated set of common codes this system "
            "recognizes. This does not mean the code is invalid."
        )
    return Citation(
        source="HCPCS Level II",
        doc_id=_CITATION_DOC_ID,
        section="Curated common-code reference",
        edition=_CITATION_EDITION,
        effective_date=None,
        excerpt=excerpt,
    )


def check_hcpcs_validity(claim: ClaimIn) -> list[Finding]:
    """
    Return a MEDIUM finding for each HCPCS-Level-II-formatted code on the
    claim that is not in the curated recognized set.

    CPT codes (5 numeric digits) never match the HCPCS format and are
    skipped entirely — this check never fires on a CPT-only claim.
    """
    findings: list[Finding] = []

    for code in dict.fromkeys(claim.cpt_codes):
        normalized = code.strip().upper()
        if not _HCPCS_FORMAT.match(normalized):
            continue
        if normalized in _KNOWN_HCPCS:
            continue

        findings.append(Finding(
            rule="hcpcs_unrecognized",
            severity="MEDIUM",
            issue=f"{normalized} is a HCPCS Level II-formatted code not in the recognized common-code set",
            recommendation=(
                "Verify this HCPCS Level II code is current and correctly transcribed. "
                "This system recognizes only a curated set of common codes — an "
                "unrecognized code is not necessarily invalid."
            ),
            citation=_citation(normalized, recognized=False),
            confidence=0.55,
        ))

    return findings
