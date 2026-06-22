"""
CMS ICD-10-CM order file-backed lookup.

Loads the CMS FY ICD-10-CM order file (fixed-width .txt) from
data/reference/icd10/ and exposes an O(1) lookup by diagnosis code.

Order file format (fixed-width, no header row):
  cols 1-5    order number
  cols 7-13   code, no decimal point (e.g. "Z00121" for Z00.121)
  col 15      billable flag — "1" billable, "0" header/category code
  cols 17-76  short description (60 chars)
  cols 77+    long description

Source: CMS ICD-10-CM — Code Descriptions in Tabular Order
Download: https://www.cms.gov/medicare/coding-billing/icd-10-codes
Refresh cadence: annual (effective October 1).
"""

from __future__ import annotations

import functools
from pathlib import Path

from rules import cms_asset_fetch

ICD10_VERSION = "FY2026"
ICD10_EFFECTIVE_DATE = "2025-10-01"
ICD10_DOC_ID = "CMS_ICD10CM_ORDER_FY2026"

_DEFAULT_DIR = "data/reference/icd10"

_CODE_START, _CODE_END = 6, 13
_BILLABLE_COL = 14
_LONG_DESC_START = 77

# Synthetic fallback entries — a small subset of real CMS ICD-10-CM codes
# and descriptions, used only when no CMS order file is present in the
# reference directory (e.g. a fresh clone, since the full file is gitignored).
# Replace by downloading the CMS ICD-10-CM order file.
_SYNTHETIC_ICD10: dict[str, dict] = {
    "Z00.00": {"description": "Encounter for general adult medical examination without abnormal findings", "billable": True, "source_file": "synthetic"},
    "Z00.01": {"description": "Encounter for general adult medical examination with abnormal findings", "billable": True, "source_file": "synthetic"},
    "Z00.121": {"description": "Encounter for routine child health examination with abnormal findings", "billable": True, "source_file": "synthetic"},
    "Z00.129": {"description": "Encounter for routine child health examination without abnormal findings", "billable": True, "source_file": "synthetic"},
    "J06.9": {"description": "Acute upper respiratory infection, unspecified", "billable": True, "source_file": "synthetic"},
    "I10": {"description": "Essential (primary) hypertension", "billable": True, "source_file": "synthetic"},
    "R10.9": {"description": "Unspecified abdominal pain", "billable": True, "source_file": "synthetic"},
    "R10.0": {"description": "Acute abdomen", "billable": True, "source_file": "synthetic"},
    "E11.9": {"description": "Type 2 diabetes mellitus without complications", "billable": True, "source_file": "synthetic"},
    "M54.5": {"description": "Low back pain, unspecified", "billable": True, "source_file": "synthetic"},
}


def _resolve_icd10_reference_dir() -> str:
    """Phase 11: prefer a populated download cache over the local reference dir.
    See rules/ncci_loader.py:_resolve_ncci_reference_dir() for the full design note."""
    cms_asset_fetch.ensure_icd10_assets()
    cache_dir = cms_asset_fetch.icd10_cache_dir()
    if list(Path(cache_dir).glob("icd10cm_order*.txt")):
        return cache_dir
    return _DEFAULT_DIR


def discover_icd10_file(reference_dir: str | None = None) -> str | None:
    """Return the path to the first CMS ICD-10-CM order .txt file found, or None."""
    if reference_dir is None:
        reference_dir = _resolve_icd10_reference_dir()
    dir_path = Path(reference_dir)
    if not dir_path.exists():
        return None
    matches = sorted(dir_path.glob("icd10cm_order*.txt"))
    return str(matches[0]) if matches else None


def _format_code(raw_code: str) -> str:
    """
    Insert the decimal point CMS omits in the order file.

    ICD-10-CM codes are 3 alpha/numeric chars before the decimal, with up to
    4 more after it (e.g. "Z00121" -> "Z00.121", "I10" -> "I10" unchanged).
    """
    raw_code = raw_code.strip().upper()
    if len(raw_code) <= 3:
        return raw_code
    return f"{raw_code[:3]}.{raw_code[3:]}"


def _load_file(fpath: str) -> dict[str, dict]:
    """Parse one CMS ICD-10-CM fixed-width order file into a code -> entry dict."""
    src_name = Path(fpath).name
    result: dict[str, dict] = {}

    with open(fpath, encoding="utf-8", errors="replace") as f:
        for line in f:
            if len(line) < _LONG_DESC_START:
                continue
            raw_code = line[_CODE_START:_CODE_END].strip()
            if not raw_code:
                continue
            billable = line[_BILLABLE_COL] == "1"
            long_desc = line[_LONG_DESC_START:].strip()

            code = _format_code(raw_code)
            if code not in result:
                result[code] = {
                    "description": long_desc,
                    "billable": billable,
                    "source_file": src_name,
                }

    return result


@functools.lru_cache(maxsize=2)
def _build_icd10_table(reference_dir: str) -> dict[str, dict]:
    """Load the CMS ICD-10-CM order file in reference_dir into a lookup dict."""
    fpath = discover_icd10_file(reference_dir)
    if fpath is None:
        return {}
    try:
        return _load_file(fpath)
    except (OSError, ValueError):
        return {}


def load_icd10_table(reference_dir: str | None = None) -> dict[str, dict]:
    """
    Return the ICD-10-CM lookup dict (file-backed if available, synthetic otherwise).

    Falls back to _SYNTHETIC_ICD10 when no CMS order file is found in reference_dir.
    reference_dir=None resolves via _resolve_icd10_reference_dir() — see
    discover_icd10_file(). An explicit override bypasses that entirely.
    """
    if reference_dir is None:
        reference_dir = _resolve_icd10_reference_dir()
    table = _build_icd10_table(reference_dir)
    return table if table else _SYNTHETIC_ICD10


def lookup_icd10(code: str, reference_dir: str | None = None) -> dict | None:
    """
    Return the ICD-10-CM entry for the given code, or None if not in the table.

    Entry dict keys: description (str), billable (bool), source_file (str).
    """
    table = load_icd10_table(reference_dir)
    return table.get(code.strip().upper())


def _clear_icd10_cache() -> None:
    """Clear the in-memory ICD-10-CM table cache (use in tests and after file updates)."""
    _build_icd10_table.cache_clear()
