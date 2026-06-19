"""
ICD-10-CM code validity and specificity check.

Looks up each diagnosis code on the claim against the CMS ICD-10-CM
reference dataset (rules/icd10_loader.py) and returns a Finding when:
  1. The code does not exist in the dataset (icd10_invalid).
  2. The code exists but its description signals an unspecified diagnosis
     (icd10_unspecified) — a lookup-based signal, not hierarchy reasoning:
     CMS descriptions for unspecified codes consistently contain the word
     "unspecified" (e.g. R10.9 "Unspecified abdominal pain").

Source: CMS ICD-10-CM — Code Descriptions in Tabular Order (see icd10_loader.py).
"""

from rules.models import Citation, ClaimIn, Finding
from rules import icd10_loader


def _citation(code: str, entry: dict | None) -> Citation:
    source_file = entry["source_file"] if entry else "n/a"
    return Citation(
        source="ICD-10-CM",
        doc_id=icd10_loader.ICD10_DOC_ID,
        section=f"ICD-10-CM Tabular Order — {code}",
        edition=icd10_loader.ICD10_VERSION,
        effective_date=icd10_loader.ICD10_EFFECTIVE_DATE,
        excerpt=f"Source: {source_file}.",
    )


def check_icd10_validity(claim: ClaimIn) -> list[Finding]:
    """
    Return a Finding for each diagnosis code that is invalid or unspecified.

    Each diagnosis code is checked once even if it appears more than once
    on the claim.
    """
    findings: list[Finding] = []

    for code in dict.fromkeys(claim.icd10_codes):
        entry = icd10_loader.lookup_icd10(code)

        if entry is None:
            findings.append(Finding(
                rule="icd10_invalid",
                severity="HIGH",
                issue=f"{code} is not a recognized ICD-10-CM diagnosis code",
                recommendation=(
                    "Confirm the diagnosis code is correctly transcribed and "
                    "current for the applicable ICD-10-CM coding year."
                ),
                citation=_citation(code, entry),
                confidence=0.95,
            ))
            continue

        if "unspecified" in entry["description"].lower():
            findings.append(Finding(
                rule="icd10_unspecified",
                severity="MEDIUM",
                issue=f"{code} ({entry['description']}) is an unspecified diagnosis",
                recommendation=(
                    "Use a more specific diagnosis code if the clinical "
                    "documentation supports it — unspecified codes draw "
                    "additional payer scrutiny."
                ),
                citation=_citation(code, entry),
                confidence=0.80,
            ))

    return findings
