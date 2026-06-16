"""
CMS NCCI MUE (Medically Unlikely Edit) file-backed lookup.

Loads CMS quarterly Practitioner Services MUE files (Excel .xlsx or .csv) from
data/reference/mue/ and exposes an O(1) lookup by HCPCS/CPT code.

MUE adjudication indicators (MAI):
  1 = Line edit — absolute hard limit per claim line; cannot be bypassed
  2 = Date-of-service edit — applies across all lines for the same DOS
  3 = Date-of-service edit with clinical rationale — documentation may allow bypass

Severity mapping:
  MAI 1 → HIGH (hard denial on any unit count above limit)
  MAI 2 or 3 → MEDIUM (may be bypassable with documentation)

Column discovery:
  CMS MUE files have changed column names across quarterly releases. This loader
  discovers columns by case-insensitive substring match rather than fixed position.
  Expected substrings: "hcpcs" or "cpt" for the code column, "mue" + "value" for
  the limit column, "adjudication" (or "mai") for the adjudication indicator column.
  The header-row scan requires ≥2 non-NaN cells with a short keyword match to
  avoid mistaking copyright paragraphs for column headers.

Source: CMS NCCI MUE — Practitioner Services
Download: https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-medically-unlikely-edits
Refresh cadence: quarterly.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

import pandas as pd

MUE_VERSION = "Q32026"
MUE_EFFECTIVE_DATE = "2026-07-01"
MUE_DOC_ID = "CMS_MUE_PRACTITIONER_Q32026"

_DEFAULT_DIR = "data/reference/mue"

# Synthetic fallback entries — plausible values, not authoritative.
# Used only when no CMS MUE files are present in the reference directory.
# Replace by downloading the quarterly CMS MUE Practitioner Services file.
_SYNTHETIC_MUE: dict[str, dict] = {
    "80053": {"mue_value": 1, "mai": "2", "source_file": "synthetic"},
    "80048": {"mue_value": 1, "mai": "2", "source_file": "synthetic"},
    "99214": {"mue_value": 1, "mai": "2", "source_file": "synthetic"},
    "99213": {"mue_value": 1, "mai": "2", "source_file": "synthetic"},
    "36415": {"mue_value": 3, "mai": "1", "source_file": "synthetic"},
    "85025": {"mue_value": 1, "mai": "2", "source_file": "synthetic"},
    "99395": {"mue_value": 1, "mai": "2", "source_file": "synthetic"},
}

MAI_DESCRIPTIONS: dict[str, str] = {
    "1": "MAI 1 — absolute per-line limit; cannot be bypassed by modifier or documentation",
    "2": "MAI 2 — date-of-service edit; applies across all claim lines for the same DOS",
    "3": "MAI 3 — date-of-service edit; additional documentation may allow bypass",
}


def discover_mue_files(reference_dir: str = _DEFAULT_DIR) -> list[str]:
    """Return sorted list of .xlsx and .csv file paths found in reference_dir."""
    dir_path = Path(reference_dir)
    if not dir_path.exists():
        return []
    xlsx = sorted(str(p) for p in dir_path.glob("*.xlsx"))
    csv = sorted(str(p) for p in dir_path.glob("*.csv"))
    return xlsx + csv


def _find_header_row(df_raw: pd.DataFrame) -> int | None:
    """
    Scan raw rows (up to the first 10) for one containing 'hcpcs' or 'cpt'.

    Returns the 0-based row index of the header row, or None if not found.
    CMS MUE files embed column names in a row after 2–5 copyright/title rows.
    Requires ≥2 non-NaN cells and a short keyword match (≤50 chars) to avoid
    matching copyright paragraphs that happen to mention "CPT".
    """
    for i, row in df_raw.head(10).iterrows():
        values = [str(v).lower() for v in row if pd.notna(v)]
        if len(values) >= 2 and any(
            ("hcpcs" in v or "cpt" in v) and len(v) <= 50 for v in values
        ):
            return int(i)
    return None


def _find_column(columns: list[str], *substrings: str) -> str | None:
    """
    Return the first column name whose lowercased value contains ALL substrings.
    Returns None if no match.
    """
    for col in columns:
        col_lower = col.lower()
        if all(s in col_lower for s in substrings):
            return col
    return None


def _load_file(fpath: str) -> dict[str, dict]:
    """
    Load one CMS MUE xlsx or csv file and return a code → entry dict.

    Raises ValueError if the required columns cannot be found.
    """
    src_name = os.path.basename(fpath)
    ext = Path(fpath).suffix.lower()

    if ext == ".xlsx":
        # Read raw to find header row, then re-read with correct skiprows
        df_raw = pd.read_excel(fpath, sheet_name=0, header=None, dtype=str, nrows=12)
        header_row = _find_header_row(df_raw)
        if header_row is None:
            raise ValueError(
                f"Could not find HCPCS/CPT header row in {src_name}. "
                "Expected a row containing 'hcpcs' or 'cpt' in the first 10 rows."
            )
        df = pd.read_excel(
            fpath,
            sheet_name=0,
            skiprows=header_row,
            header=0,
            dtype=str,
        )
    else:
        # CSV: try with header on first row; fall back to scanning if needed
        df_raw = pd.read_csv(fpath, header=None, dtype=str, nrows=12)
        header_row = _find_header_row(df_raw)
        if header_row is None:
            header_row = 0
        df = pd.read_csv(fpath, skiprows=header_row, header=0, dtype=str)

    # Strip column names
    df.columns = [str(c).strip() for c in df.columns]
    cols = list(df.columns)

    # Discover code column
    code_col = _find_column(cols, "hcpcs") or _find_column(cols, "cpt")
    if code_col is None:
        raise ValueError(
            f"Could not find HCPCS/CPT code column in {src_name}. "
            f"Available columns: {cols}"
        )

    # Discover MUE value column
    mue_col = _find_column(cols, "mue", "value") or _find_column(cols, "mue")
    if mue_col is None:
        raise ValueError(
            f"Could not find MUE value column in {src_name}. "
            f"Available columns: {cols}"
        )

    # Discover MAI column — CMS has used both "MAI" and "MUE Adjudication Indicator"
    mai_col = _find_column(cols, "mai") or _find_column(cols, "adjudication")
    if mai_col is None:
        raise ValueError(
            f"Could not find MAI/adjudication column in {src_name}. "
            f"Available columns: {cols}"
        )

    result: dict[str, dict] = {}
    for _, row in df.iterrows():
        code_raw = str(row[code_col]).strip()
        mue_raw = str(row[mue_col]).strip()
        mai_raw = str(row[mai_col]).strip()

        # Skip blank, header-repeat, or zero-limit rows
        if not code_raw or code_raw.lower() in ("nan", "hcpcs", "cpt", "hcpcs / cpt code"):
            continue
        try:
            mue_value = int(float(mue_raw))
        except (ValueError, TypeError):
            continue
        if mue_value <= 0:
            continue

        # Normalize MAI — extract leading digit from values like "2 Date of Service Edit: Policy"
        mai = mai_raw[0] if mai_raw and mai_raw[0].isdigit() else ""
        if mai not in ("1", "2", "3"):
            continue

        code = code_raw.upper()
        if code not in result:
            result[code] = {
                "mue_value": mue_value,
                "mai": mai,
                "source_file": src_name,
            }

    return result


@functools.lru_cache(maxsize=4)
def _build_mue_table(reference_dir: str) -> dict[str, dict]:
    """
    Load all MUE files in reference_dir and merge into a single lookup dict.

    Key: HCPCS/CPT code (uppercase string)
    Value: {"mue_value": int, "mai": str, "source_file": str}

    If multiple files define the same code, the first file wins (files are
    processed in sorted order so the result is deterministic).
    """
    files = discover_mue_files(reference_dir)
    if not files:
        return {}

    merged: dict[str, dict] = {}
    for fpath in files:
        try:
            entries = _load_file(fpath)
        except (ValueError, Exception):
            # Don't let a malformed file break the whole load; skip it
            continue
        for code, entry in entries.items():
            if code not in merged:
                merged[code] = entry

    return merged


def load_mue_table(reference_dir: str = _DEFAULT_DIR) -> dict[str, dict]:
    """
    Return the MUE lookup dict (file-backed if available, synthetic otherwise).

    Falls back to _SYNTHETIC_MUE when no CMS files are found in reference_dir.
    """
    table = _build_mue_table(reference_dir)
    return table if table else _SYNTHETIC_MUE


def lookup_mue(code: str, reference_dir: str = _DEFAULT_DIR) -> dict | None:
    """
    Return MUE entry for the given HCPCS/CPT code, or None if not in the table.

    Entry dict keys: mue_value (int), mai (str "1"/"2"/"3"), source_file (str).
    """
    table = load_mue_table(reference_dir)
    return table.get(code.strip().upper())


def _clear_mue_cache() -> None:
    """Clear the in-memory MUE table cache (use in tests and after file updates)."""
    _build_mue_table.cache_clear()
