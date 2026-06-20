"""
Reference data source status (TD-27).

Each file-backed loader (ncci_loader, mue_loader, icd10_loader) already knows
whether it found real CMS reference files in data/reference/ or is serving
its small hardcoded synthetic fallback. This module exposes that status
programmatically in one place, so callers (tests, a future UI, ops tooling)
don't have to know about each loader's internal discovery function.

Backend-only per TD-27 scope: no UI indicator is added here. Build a UI
status display as a separate UI Polish task if desired.
"""

from __future__ import annotations

from rules import icd10_loader, mue_loader, ncci_loader

_FILE_BACKED = "file_backed"
_SYNTHETIC_FALLBACK = "synthetic_fallback"


def _ncci_status() -> dict:
    files = ncci_loader.discover_ncci_files()
    is_file_backed = bool(files) and bool(ncci_loader.load_ncci_ptp_edits())
    return {
        "status": _FILE_BACKED if is_file_backed else _SYNTHETIC_FALLBACK,
        "version": ncci_loader.NCCI_VERSION if is_file_backed else "synthetic fallback",
        "effective_date": ncci_loader.NCCI_EFFECTIVE_DATE if is_file_backed else None,
        "files_found": files,
    }


def _mue_status() -> dict:
    files = mue_loader.discover_mue_files()
    is_file_backed = bool(files) and bool(mue_loader.load_mue_table())
    return {
        "status": _FILE_BACKED if is_file_backed else _SYNTHETIC_FALLBACK,
        "version": mue_loader.MUE_VERSION if is_file_backed else "synthetic fallback",
        "effective_date": mue_loader.MUE_EFFECTIVE_DATE if is_file_backed else None,
        "files_found": files,
    }


def _icd10_status() -> dict:
    fpath = icd10_loader.discover_icd10_file()
    is_file_backed = fpath is not None and bool(icd10_loader.load_icd10_table())
    return {
        "status": _FILE_BACKED if is_file_backed else _SYNTHETIC_FALLBACK,
        "version": icd10_loader.ICD10_VERSION if is_file_backed else "synthetic fallback",
        "effective_date": icd10_loader.ICD10_EFFECTIVE_DATE if is_file_backed else None,
        "files_found": [fpath] if fpath else [],
    }


def get_data_source_status() -> dict:
    """
    Return per-dataset status for every file-backed reference loader.

    Each value is a dict with keys: status ("file_backed" | "synthetic_fallback"),
    version, effective_date, files_found (list of discovered file paths, [] if none).

    This reflects each loader's lru_cache state at call time — if a loader has
    already been called once in this process and cached an empty result, this
    will also report synthetic_fallback even if files were since added (same
    cache-lifetime behavior the loaders themselves already document).
    """
    return {
        "ncci": _ncci_status(),
        "mue": _mue_status(),
        "icd10": _icd10_status(),
    }


def any_synthetic_fallback_active() -> bool:
    """True if at least one dataset is currently running on its synthetic fallback."""
    status = get_data_source_status()
    return any(v["status"] == _SYNTHETIC_FALLBACK for v in status.values())
