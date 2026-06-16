"""
NCCI PTP (Procedure-to-Procedure) edit table lookups.

Backed by CMS NCCI Practitioner PTP Excel files loaded via ncci_loader.
Falls back to a single hardcoded synthetic pair when no CMS files are present,
preserving demo behavior in environments without the reference data.

Production path: place CMS quarterly xlsx files in data/reference/ncci/ and
restart. The public interface (check_ncci_pairs) is unchanged.

Modifier indicator values:
  0 = no modifier bypass allowed (hard bundle)
  1 = bypass allowed with an appropriate modifier
  9 = not applicable
"""

from __future__ import annotations

from itertools import combinations

from rules.models import Citation, ClaimIn, Finding
from rules import ncci_loader


# ---------------------------------------------------------------------------
# Synthetic fallback — used only when no CMS xlsx files are available
# ---------------------------------------------------------------------------

_SYNTHETIC_EDITS = [
    {
        "col1": "80053",
        "col2": "80048",
        "modifier": "0",
        "doc_id": "NCCI_PTP_80048_80053_SAMPLE",
        "section": "Physician/Practitioner PTP Edit Table, Column 1 / Column 2",
        "edition": (
            "NCCI Policy Manual for Medicare Services "
            "(synthetic fallback — CMS files not available)"
        ),
        "effective_date": "2000-01-01",
        "excerpt": (
            "CPT code 80048 (Basic Metabolic Panel) is a component of CPT code "
            "80053 (Comprehensive Metabolic Panel). Separate billing of 80048 "
            "alongside 80053 on the same date of service constitutes unbundling. "
            "Modifier indicator 0: no modifier bypass is permitted for this pair. "
            "[SYNTHETIC FALLBACK: CMS NCCI files not found in data/reference/ncci/. "
            "Place quarterly xlsx files there to enable file-backed validation.]"
        ),
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _recommendation(col1: str, col2: str, modifier: str) -> str:
    if modifier == "0":
        note = "No modifier bypass is allowed; these codes cannot be billed separately."
    elif modifier == "1":
        note = (
            "A modifier may allow separate reimbursement if clinically appropriate "
            "and documented — confirm before adding."
        )
    else:
        note = "Edit is not applicable or not active for this code pair."
    return f"Remove {col2} when billed with {col1}. {note}"


def _file_backed_finding(result: dict) -> Finding:
    """Build a Finding from a ncci_loader.lookup_ncci_pair() result dict."""
    col1 = result["col1"]
    col2 = result["col2"]
    modifier = result["modifier"]
    source_file = result["source_file"]
    pair_date = result["pair_effective_date"]

    # Convert YYYYMMDD → YYYY-MM-DD for display
    if len(pair_date) == 8 and pair_date.isdigit():
        pair_date_fmt = f"{pair_date[:4]}-{pair_date[4:6]}-{pair_date[6:]}"
    else:
        pair_date_fmt = pair_date

    modifier_desc = result.get("modifier_description", "")

    excerpt = (
        f"CMS NCCI Practitioner PTP Edit Table {ncci_loader.NCCI_VERSION} "
        f"(effective {ncci_loader.NCCI_EFFECTIVE_DATE}): "
        f"{col2} (component) is a component of {col1} (comprehensive). "
        f"Modifier indicator {modifier}: {modifier_desc} "
        f"This edit pair has been in effect since {pair_date_fmt}. "
        f"Source: {source_file}."
    )

    return Finding(
        rule="ncci_ptp",
        severity="HIGH",
        issue=(
            f"{col2} is bundled with {col1} "
            f"(NCCI Practitioner PTP edit, {ncci_loader.NCCI_VERSION})"
        ),
        recommendation=_recommendation(col1, col2, modifier),
        citation=Citation(
            source="NCCI",
            doc_id=ncci_loader.NCCI_DOC_ID,
            section="Practitioner PTP Edits",
            edition=ncci_loader.NCCI_VERSION,
            effective_date=ncci_loader.NCCI_EFFECTIVE_DATE,
            excerpt=excerpt,
        ),
        confidence=0.98,
        source="rule_layer",
    )


def _synthetic_finding(edit: dict) -> Finding:
    """Build a Finding from a hardcoded synthetic edit dict (fallback path)."""
    col1 = edit["col1"]
    col2 = edit["col2"]
    modifier = edit["modifier"]

    return Finding(
        rule="ncci_ptp",
        severity="HIGH",
        issue=f"Bundled code pair: {col2} is a component of {col1}",
        recommendation=_recommendation(col1, col2, modifier),
        citation=Citation(
            source="NCCI PTP",
            doc_id=edit["doc_id"],
            section=edit["section"],
            edition=edit["edition"],
            effective_date=edit["effective_date"],
            excerpt=edit["excerpt"],
        ),
        confidence=0.95,
        source="rule_layer",
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def check_ncci_pairs(claim: ClaimIn) -> list[Finding]:
    """
    Return a Finding for each active NCCI PTP edit pair present in the claim.

    Loads CMS quarterly xlsx files from data/reference/ncci/ on first call
    (cached for the process lifetime). Falls back to the hardcoded synthetic
    pair list if no CMS files are found.

    Finding severity is always HIGH: an NCCI bundling conflict is a certain
    denial if left uncorrected.
    """
    findings: list[Finding] = []
    code_set: set[str] = set(claim.cpt_codes)

    edit_table = ncci_loader.load_ncci_ptp_edits()

    if edit_table:
        # File-backed path: check every unique pair of codes in the claim
        for code_a, code_b in combinations(sorted(code_set), 2):
            result = ncci_loader.lookup_ncci_pair(code_a, code_b)
            if result:
                findings.append(_file_backed_finding(result))
    else:
        # Synthetic fallback: fires only when no CMS xlsx files are available
        for edit in _SYNTHETIC_EDITS:
            if edit["col1"] in code_set and edit["col2"] in code_set:
                findings.append(_synthetic_finding(edit))

    return findings
