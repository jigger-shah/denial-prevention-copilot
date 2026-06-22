"""
Optional CMS reference asset auto-download from GitHub Release Assets (Phase 11).

Hosted deployments (e.g. Streamlit Cloud) have no local copy of the real CMS
NCCI/MUE/ICD-10 reference files — they're gitignored (~266MB combined, see
docs/Technical_Debt_Register.md TD-27). This module optionally downloads them
from maintainer-configured GitHub Release Asset URLs into a temp-dir cache, so
hosted deployments can run file-backed instead of synthetic-fallback when the
maintainer has published assets — with no effect at all when they haven't.

Design constraints (all deliberate, mirroring existing patterns in this codebase):
  - No required secrets: every URL is optional. Unset = skip silently, behave
    exactly as before this module existed.
  - No hardcoded fallback URLs of any kind, attachment or release — every URL
    comes from configuration only.
  - Lazy, not at import time: nothing here runs until a loader's discover/load
    function is actually called with reference_dir=None (the "no override"
    default path). Mirrors agents/coverage_validation.py's lazy VectorStore
    construction and db/audit_repository.py's lazy schema init.
  - Attempted at most once per process: each ensure_*_assets() is
    @lru_cache(maxsize=1)'d (no-arg) so a slow or failing download is never
    retried on every claim review within the same process — same "once per
    process lifetime" philosophy already used for the NCCI/MUE/ICD-10 tables
    themselves, the ChromaDB VectorStore singleton, and the data-source-status
    cache.
  - Cache lives under tempfile.gettempdir(), never inside the repo tree — same
    reasoning as db/audit_repository.py's DB_PATH: Streamlit Cloud's
    filesystem is ephemeral, so a temp-dir cache makes the
    reset-on-restart/redeploy/sleep behavior explicit rather than accidental.
    A fresh process re-downloads once, lazily, on first access — it does not
    "remember" across restarts, by design.
  - Never raises: every failure (missing config, network error, timeout,
    non-200, zero-byte response) is caught, logged at WARNING, and degrades to
    "not cached" — callers always fall back to the existing local
    data/reference/ directory, and from there to each loader's existing
    synthetic fallback table, completely unchanged.
  - Atomic writes: download to a .part file in the destination directory, then
    os.replace() into place — a crash or interrupted download can never leave
    a corrupt-but-present file that a later run mistakes for a valid cache hit.

get_secret()-equivalent resolution is duplicated here (env var, then
st.secrets) rather than imported from agents/secrets.py, deliberately — this
is the rules/ layer, which agents/ depends on, not the reverse; importing
from agents/ here would invert that documented dependency direction for a
~8-line helper.
"""

from __future__ import annotations

import functools
import logging
import os
import pathlib
import tempfile

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = (5, 30)  # (connect, read) seconds — generous but bounded; see module docstring

_CACHE_ROOT = pathlib.Path(tempfile.gettempdir()) / "denial_copilot_cms_cache"

# env var name -> (cache subdir, cache filename)
_NCCI_ASSETS = {
    "CMS_NCCI_F1_URL": "ccipra_f1.xlsx",
    "CMS_NCCI_F2_URL": "ccipra_f2.xlsx",
    "CMS_NCCI_F3_URL": "ccipra_f3.xlsx",
    "CMS_NCCI_F4_URL": "ccipra_f4.xlsx",
}
_MUE_ASSETS = {
    "CMS_MUE_URL": "mue_practitioner.xlsx",
}
_ICD10_ASSETS = {
    # Must match rules/icd10_loader.py:discover_icd10_file()'s "icd10cm_order*.txt" glob.
    "CMS_ICD10_URL": "icd10cm_order_downloaded.txt",
}


def ncci_cache_dir() -> str:
    return str(_CACHE_ROOT / "ncci")


def mue_cache_dir() -> str:
    return str(_CACHE_ROOT / "mue")


def icd10_cache_dir() -> str:
    return str(_CACHE_ROOT / "icd10")


def _resolve_config(name: str) -> str:
    """Resolve a config value: OS environment variable, then Streamlit secrets, then "".

    Duplicated from agents/secrets.py:get_secret() rather than imported — see
    module docstring. Behavior is identical: env var first (local .env via
    python-dotenv, unchanged), st.secrets fallback wrapped in try/except since
    it raises with no .streamlit/secrets.toml present (normal for local dev).
    """
    val = os.getenv(name)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(name, "")
    except Exception:
        return ""


def _download_to_cache(url: str, dest_path: pathlib.Path) -> tuple[bool, str | None]:
    """
    Download url to dest_path atomically. Returns (success, error_message).

    Never raises. Validates HTTP status and that the downloaded file is
    non-empty before the atomic rename — a failed/partial/empty download
    never replaces an existing valid cache entry, and never leaves a
    zero-byte file in dest_path's place.
    """
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=_TIMEOUT) as resp:
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        return False, str(exc)

    if not tmp_path.exists() or tmp_path.stat().st_size == 0:
        tmp_path.unlink(missing_ok=True)
        return False, "downloaded file was empty"

    os.replace(tmp_path, dest_path)
    return True, None


def _ensure_assets(asset_map: dict[str, str], cache_dir: str) -> dict:
    """
    For each (env_var, filename) in asset_map, download into cache_dir if the
    env var is configured and the file isn't already cached. Never raises.

    Returns {"attempted": bool, "succeeded": list[str], "errors": dict[str, str]}.
    "attempted" is True iff at least one URL was configured (i.e. a download
    was actually tried) — used by data_source_status.py to distinguish "no
    URLs configured" from "configured but failed" when explaining fallback.
    """
    result = {"attempted": False, "succeeded": [], "errors": {}}
    cache_path = pathlib.Path(cache_dir)

    for env_var, filename in asset_map.items():
        dest = cache_path / filename
        if dest.exists() and dest.stat().st_size > 0:
            result["succeeded"].append(filename)
            continue

        url = _resolve_config(env_var)
        if not url:
            continue  # not configured — skip silently, no attempt made

        result["attempted"] = True
        ok, error = _download_to_cache(url, dest)
        if ok:
            result["succeeded"].append(filename)
        else:
            logger.warning("CMS asset download failed for %s: %s", env_var, error)
            result["errors"][env_var] = error

    return result


@functools.lru_cache(maxsize=1)
def ensure_ncci_assets() -> dict:
    """Attempt the 4 configured NCCI asset downloads, at most once per process."""
    return _ensure_assets(_NCCI_ASSETS, ncci_cache_dir())


@functools.lru_cache(maxsize=1)
def ensure_mue_assets() -> dict:
    """Attempt the configured MUE asset download, at most once per process."""
    return _ensure_assets(_MUE_ASSETS, mue_cache_dir())


@functools.lru_cache(maxsize=1)
def ensure_icd10_assets() -> dict:
    """Attempt the configured ICD-10 asset download, at most once per process."""
    return _ensure_assets(_ICD10_ASSETS, icd10_cache_dir())


def _clear_cms_asset_cache() -> None:
    """Clear in-memory ensure_*_assets() memoization (tests only). Does not
    delete any cached files on disk — same convention as the loaders' own
    _clear_*_cache() helpers, which never touch the filesystem either."""
    ensure_ncci_assets.cache_clear()
    ensure_mue_assets.cache_clear()
    ensure_icd10_assets.cache_clear()
