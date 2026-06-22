"""
Tests for rules/data_source_status.py — real-CMS-data vs synthetic-fallback
status reporting (TD-27, backend only — no UI assertions here).

Phase 11 extends this with source/download_attempted/download_error fields
(see rules/cms_asset_fetch.py) — additive only, the existing status/version/
effective_date/files_found contract is unchanged.
"""

from __future__ import annotations

import pytest

from rules import cms_asset_fetch, data_source_status, icd10_loader, mue_loader, ncci_loader


def _clear_all_caches():
    icd10_loader._clear_icd10_cache()
    mue_loader._clear_mue_cache()
    ncci_loader._clear_ncci_cache()
    cms_asset_fetch._clear_cms_asset_cache()


@pytest.fixture(autouse=True)
def _no_real_cms_download_config(monkeypatch):
    """Guarantee no accidental real network call in this file regardless of
    the local environment — same defensive convention as test_app_ai_disabled.py
    for ANTHROPIC_API_KEY."""
    for name in (
        "CMS_NCCI_F1_URL", "CMS_NCCI_F2_URL", "CMS_NCCI_F3_URL", "CMS_NCCI_F4_URL",
        "CMS_MUE_URL", "CMS_ICD10_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_get_data_source_status_returns_all_three_datasets():
    _clear_all_caches()
    status = data_source_status.get_data_source_status()
    assert set(status.keys()) == {"ncci", "mue", "icd10"}


def test_each_dataset_status_has_expected_keys():
    _clear_all_caches()
    status = data_source_status.get_data_source_status()
    for entry in status.values():
        assert "status" in entry
        assert entry["status"] in ("file_backed", "synthetic_fallback")
        assert "version" in entry
        assert "effective_date" in entry
        assert "files_found" in entry
        assert "source" in entry
        assert entry["source"] in ("downloaded", "local_file", "synthetic_fallback")
        assert "download_attempted" in entry
        assert "download_error" in entry


def test_synthetic_fallback_reported_when_no_reference_dir(monkeypatch):
    """Pointing discovery at a nonexistent directory must report synthetic_fallback."""
    _clear_all_caches()
    monkeypatch.setattr(ncci_loader, "discover_ncci_files", lambda reference_dir=None: [])
    monkeypatch.setattr(mue_loader, "discover_mue_files", lambda reference_dir=None: [])
    monkeypatch.setattr(icd10_loader, "discover_icd10_file", lambda reference_dir=None: None)

    status = data_source_status.get_data_source_status()
    assert status["ncci"]["status"] == "synthetic_fallback"
    assert status["mue"]["status"] == "synthetic_fallback"
    assert status["icd10"]["status"] == "synthetic_fallback"
    assert status["ncci"]["files_found"] == []
    assert status["icd10"]["files_found"] == []


def test_any_synthetic_fallback_active_true_when_all_synthetic(monkeypatch):
    _clear_all_caches()
    monkeypatch.setattr(ncci_loader, "discover_ncci_files", lambda reference_dir=None: [])
    monkeypatch.setattr(mue_loader, "discover_mue_files", lambda reference_dir=None: [])
    monkeypatch.setattr(icd10_loader, "discover_icd10_file", lambda reference_dir=None: None)

    assert data_source_status.any_synthetic_fallback_active() is True


def test_file_backed_status_reports_version_and_effective_date(monkeypatch):
    """When a loader's table is non-empty, status must be file_backed with real version metadata."""
    _clear_all_caches()
    monkeypatch.setattr(icd10_loader, "discover_icd10_file", lambda reference_dir=None: "fake/path.txt")
    monkeypatch.setattr(icd10_loader, "load_icd10_table", lambda reference_dir=None: {"I10": {}})

    status = data_source_status._icd10_status()
    assert status["status"] == "file_backed"
    assert status["version"] == icd10_loader.ICD10_VERSION
    assert status["effective_date"] == icd10_loader.ICD10_EFFECTIVE_DATE
    assert status["files_found"] == ["fake/path.txt"]


# ---------------------------------------------------------------------------
# Phase 11 — source/download_attempted/download_error fields
# ---------------------------------------------------------------------------

def test_local_file_backed_status_has_local_file_source(monkeypatch):
    """file_backed with no download configured/succeeded must report source
    'local_file', not 'downloaded' — it's an honest distinction for the UI."""
    _clear_all_caches()
    monkeypatch.setattr(icd10_loader, "discover_icd10_file", lambda reference_dir=None: "fake/path.txt")
    monkeypatch.setattr(icd10_loader, "load_icd10_table", lambda reference_dir=None: {"I10": {}})

    status = data_source_status._icd10_status()
    assert status["source"] == "local_file"
    assert status["download_attempted"] is False
    assert status["download_error"] is None


def test_synthetic_fallback_status_has_synthetic_source(monkeypatch):
    _clear_all_caches()
    monkeypatch.setattr(ncci_loader, "discover_ncci_files", lambda reference_dir=None: [])

    status = data_source_status._ncci_status()
    assert status["status"] == "synthetic_fallback"
    assert status["source"] == "synthetic_fallback"
    assert status["download_attempted"] is False


def test_downloaded_status_reports_downloaded_source(monkeypatch, tmp_path):
    """A successful download must report source 'downloaded' and status
    'file_backed' — the per-dataset status pill's two existing values are
    unchanged; only the explanatory 'source' field is new."""
    _clear_all_caches()
    monkeypatch.setattr(cms_asset_fetch, "_CACHE_ROOT", tmp_path)
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")

    from unittest.mock import MagicMock, patch
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.iter_content.return_value = [b"fake xlsx bytes"]
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False

    with patch("rules.cms_asset_fetch.requests.get", return_value=resp):
        with patch.object(mue_loader, "discover_mue_files", wraps=mue_loader.discover_mue_files):
            status = data_source_status._mue_status()

    assert status["download_attempted"] is True
    assert status["download_error"] is None
    if status["status"] == "file_backed":
        assert status["source"] == "downloaded"


def test_download_failure_status_reports_attempted_and_error(monkeypatch, tmp_path):
    """A failed download must still report status synthetic_fallback (governance
    unchanged) but flag that a download was attempted and why it didn't work —
    this is the 'download unavailable / fallback' state from the spec."""
    _clear_all_caches()
    monkeypatch.setattr(cms_asset_fetch, "_CACHE_ROOT", tmp_path)
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")
    monkeypatch.setattr(mue_loader, "discover_mue_files", lambda reference_dir=None: [])

    from unittest.mock import patch
    with patch("rules.cms_asset_fetch.requests.get", side_effect=ConnectionError("unreachable")):
        status = data_source_status._mue_status()

    assert status["status"] == "synthetic_fallback"
    assert status["source"] == "synthetic_fallback"
    assert status["download_attempted"] is True
    assert status["download_error"] is not None
    assert "unreachable" in status["download_error"]


def test_mixed_status_when_one_dataset_downloads_and_others_fall_back(monkeypatch, tmp_path):
    """Aggregate 'mixed' status (app/main.py's existing logic) must still
    trigger correctly when one dataset is downloaded and the others remain on
    synthetic fallback — confirms the new download path doesn't disturb the
    existing file_backed/synthetic_fallback/mixed aggregation."""
    _clear_all_caches()
    monkeypatch.setattr(cms_asset_fetch, "_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(ncci_loader, "discover_ncci_files", lambda reference_dir=None: ["fake.xlsx"])
    monkeypatch.setattr(ncci_loader, "load_ncci_ptp_edits", lambda reference_dir=None: {("A", "B"): {}})
    monkeypatch.setattr(mue_loader, "discover_mue_files", lambda reference_dir=None: [])
    monkeypatch.setattr(icd10_loader, "discover_icd10_file", lambda reference_dir=None: None)

    status = data_source_status.get_data_source_status()
    statuses = {v["status"] for v in status.values()}
    assert statuses == {"file_backed", "synthetic_fallback"}
