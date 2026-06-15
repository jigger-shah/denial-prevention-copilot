"""
NCCI PTP (Procedure-to-Procedure) edit table lookups.

Sprint 1: backed by a hardcoded sample edit table.
Production path: replace _load_ptp_edits() with a CSV loader that reads
the CMS quarterly PTP file from data/reference/ncci_ptp_<quarter>.csv.
The public interface (check_ncci_pairs) stays the same.

Modifier indicator values:
  0 = no modifier bypass allowed (hard bundle)
  1 = bypass allowed with an appropriate modifier
  9 = not applicable
"""

from rules.models import Citation, ClaimIn, Finding


# ---------------------------------------------------------------------------
# Data source — swap this function to load from the real CMS CSV in production
# ---------------------------------------------------------------------------

def _load_ptp_edits() -> list[dict]:
    """
    Returns PTP edit rules as a list of dicts.

    Each entry represents one CMS NCCI PTP edit pair:
      col1:               comprehensive (column 1) code
      col2:               component (column 2) code — the one to remove
      modifier_indicator: 0 | 1 | 9
      doc_id:             versioned document identifier (quarter string in production)
      edition:            human-readable version label
      effective_date:     ISO date when this edit became effective (None for synthetic)
    """
    return [
        {
            "col1": "80053",
            "col2": "80048",
            "modifier_indicator": 0,
            "doc_id": "NCCI-PTP-SYNTHETIC",
            "edition": "synthetic sample",
            "effective_date": None,
        },
    ]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def check_ncci_pairs(claim: ClaimIn) -> list[Finding]:
    """
    Return a Finding for each NCCI PTP edit pair present in the claim.

    A HIGH-severity finding is raised whenever both the column-1 and column-2
    codes appear on the same claim.  Modifier indicator 0 means no bypass is
    possible; indicator 1 means a modifier could resolve it (noted in the
    recommendation).
    """
    findings = []
    code_set = set(claim.cpt_codes)

    for edit in _load_ptp_edits():
        col1 = edit["col1"]
        col2 = edit["col2"]
        if col1 not in code_set or col2 not in code_set:
            continue

        if edit["modifier_indicator"] == 0:
            bypass_note = "No modifier bypass is allowed for this pair."
        elif edit["modifier_indicator"] == 1:
            bypass_note = (
                "A modifier may allow separate billing if clinically "
                "appropriate — confirm before adding."
            )
        else:
            bypass_note = ""

        findings.append(Finding(
            rule="ncci_ptp",
            severity="HIGH",
            issue=f"Bundled code pair: {col2} is a component of {col1}",
            recommendation=(
                f"Remove {col2} when billed with {col1}. {bypass_note}"
            ).strip(),
            citation=Citation(
                source="NCCI PTP",
                doc_id=edit["doc_id"],
                section="Physician/Practitioner PTP edit table, Column 1 / Column 2",
                edition=edit["edition"],
                effective_date=edit["effective_date"],
                excerpt=(
                    f"{col1} (col 1) / {col2} (col 2) — "
                    f"modifier indicator {edit['modifier_indicator']}"
                ),
            ),
            confidence=0.95,
        ))

    return findings
