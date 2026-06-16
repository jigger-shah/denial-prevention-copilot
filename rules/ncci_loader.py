"""
NCCI Practitioner PTP file-backed lookup.

Loads CMS NCCI Practitioner PTP edit files (Excel .xlsx format) from a local
reference directory and provides O(1) lookup by code pair.

File format (CMS quarterly release):
  - 6-row header block (copyright, title, column legends)
  - Data rows: col1, col2, prior_1996, effective_date, deletion_date, modifier, rationale
  - deletion_date == "*" means the edit is still active (no deletion)
  - modifier: "0" = no bypass, "1" = modifier may bypass, "9" = not applicable

Current reference version: v322r0, effective 2026-07-01
Source files: ccipra-v322r0-f1.xlsx through ccipra-v322r0-f4.xlsx
Download: https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits

To update to a new quarterly release:
  1. Download the new Practitioner PTP files from the CMS NCCI page.
  2. Place them in data/reference/ncci/ (replace or add files).
  3. Update NCCI_VERSION and NCCI_EFFECTIVE_DATE below.
  4. Restart the application (the cache will repopulate on first review).

Performance note:
  First call to load_ncci_ptp_edits() reads ~2.6M rows from 4 Excel files and
  takes approximately 50–60 seconds. Results are cached in memory for the
  lifetime of the Python process (via functools.lru_cache). Subsequent lookups
  are O(1) dict access. In the Streamlit app, the first "Review Claim" in a
  session triggers the load; all subsequent reviews are instant.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

import pandas as pd

NCCI_VERSION = "v322r0"
NCCI_EFFECTIVE_DATE = "2026-07-01"
NCCI_DOC_ID = "CMS_NCCI_PTP_v322r0"

_DEFAULT_DIR = "data/reference/ncci"
_HEADER_ROWS = 6
_ACTIVE_MARKER = "*"

# Column positions in the CMS xlsx (0-indexed, after skipping the header block)
_COL_IDX_COL1 = 0
_COL_IDX_COL2 = 1
_COL_IDX_EFF_DATE = 3
_COL_IDX_DEL_DATE = 4
_COL_IDX_MODIFIER = 5

_MODIFIER_DESCRIPTIONS = {
    "0": "No modifier bypass is allowed; these codes cannot be billed separately.",
    "1": "A modifier may allow separate reimbursement if clinically appropriate and documented.",
    "9": "Edit is not applicable or not active for this code pair.",
}


def discover_ncci_files(reference_dir: str = _DEFAULT_DIR) -> list[str]:
    """Return sorted list of .xlsx file paths found in reference_dir."""
    dir_path = Path(reference_dir)
    if not dir_path.exists():
        return []
    return sorted(str(p) for p in dir_path.glob("*.xlsx"))


def inspect_ncci_files(reference_dir: str = _DEFAULT_DIR) -> list[dict]:
    """
    Return inspection metadata for each NCCI Excel file.

    Reads only the first few rows for speed — use for diagnostics, not lookup.
    """
    results = []
    for fpath in discover_ncci_files(reference_dir):
        fname = os.path.basename(fpath)
        df_full = pd.read_excel(
            fpath,
            sheet_name=0,
            skiprows=_HEADER_ROWS,
            header=None,
            usecols=[_COL_IDX_COL1, _COL_IDX_COL2, _COL_IDX_DEL_DATE, _COL_IDX_MODIFIER],
            names=["col1", "col2", "deletion_date", "modifier"],
            dtype=str,
        )
        df_full["deletion_date"] = df_full["deletion_date"].str.strip()
        active = df_full[df_full["deletion_date"] == _ACTIVE_MARKER]
        results.append({
            "file": fname,
            "total_rows": len(df_full),
            "active_rows": len(active),
            "sample_active": (
                active[["col1", "col2", "modifier"]]
                .head(3)
                .to_dict("records")
            ),
        })
    return results


@functools.lru_cache(maxsize=8)
def _build_edit_table(reference_dir: str) -> dict[tuple[str, str], dict]:
    """
    Load all NCCI xlsx files in reference_dir and build a lookup dict.

    Key: (col1, col2) tuple of normalized uppercase strings
    Value: {"modifier": str, "source_file": str, "pair_effective_date": str}

    Only active edits (deletion_date == "*") are included.
    Cached per reference_dir via lru_cache.
    """
    files = discover_ncci_files(reference_dir)
    if not files:
        return {}

    lookup: dict[tuple[str, str], dict] = {}

    for fpath in files:
        src_name = os.path.basename(fpath)
        df = pd.read_excel(
            fpath,
            sheet_name=0,
            skiprows=_HEADER_ROWS,
            header=None,
            usecols=[
                _COL_IDX_COL1,
                _COL_IDX_COL2,
                _COL_IDX_EFF_DATE,
                _COL_IDX_DEL_DATE,
                _COL_IDX_MODIFIER,
            ],
            names=["col1", "col2", "eff_date", "del_date", "modifier"],
            dtype=str,
        )

        for col in ["col1", "col2", "del_date", "modifier"]:
            df[col] = df[col].str.strip()

        active = df[df["del_date"] == _ACTIVE_MARKER]

        for row in active.itertuples(index=False):
            key = (row.col1.upper(), row.col2.upper())
            if key not in lookup:
                raw_date = str(row.eff_date).strip().split(".")[0]  # remove any .0
                lookup[key] = {
                    "modifier": row.modifier,
                    "source_file": src_name,
                    "pair_effective_date": raw_date,
                }

    return lookup


def load_ncci_ptp_edits(reference_dir: str = _DEFAULT_DIR) -> dict:
    """
    Return the NCCI PTP edit lookup dict (cached after first load).

    Returns an empty dict if no Excel files are found in reference_dir.
    To reload after adding new files, call _clear_ncci_cache() first.
    """
    return _build_edit_table(reference_dir)


def _clear_ncci_cache() -> None:
    """Clear the in-memory NCCI edit table cache (use in tests and after file updates)."""
    _build_edit_table.cache_clear()


def lookup_ncci_pair(
    code_a: str,
    code_b: str,
    reference_dir: str = _DEFAULT_DIR,
) -> dict | None:
    """
    Return NCCI edit details if code_a and code_b form an active PTP edit pair.

    Checks both (code_a, code_b) and (code_b, code_a) since CMS files are
    directional: col1 is the comprehensive code (keep it), col2 is the component
    (the one that should not be billed separately).

    Returns a dict with keys:
        col1            comprehensive code (keep)
        col2            component code (remove)
        modifier        "0", "1", or "9"
        source_file     xlsx filename where the pair was found
        pair_effective_date  YYYYMMDD string from the CMS file
        modifier_description  human-readable modifier explanation

    Returns None if no active edit pair exists.
    """
    table = load_ncci_ptp_edits(reference_dir)
    if not table:
        return None

    a = code_a.strip().upper()
    b = code_b.strip().upper()

    for ca, cb in [(a, b), (b, a)]:
        entry = table.get((ca, cb))
        if entry:
            modifier = entry["modifier"]
            return {
                "col1": ca,
                "col2": cb,
                "modifier": modifier,
                "source_file": entry["source_file"],
                "pair_effective_date": entry["pair_effective_date"],
                "modifier_description": _MODIFIER_DESCRIPTIONS.get(modifier, ""),
            }

    return None
