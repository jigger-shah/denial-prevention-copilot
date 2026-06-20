"""
Tests for rules/data_source_status.py — real-CMS-data vs synthetic-fallback
status reporting (TD-27, backend only — no UI assertions here).
"""

from __future__ import annotations

from rules import data_source_status, icd10_loader, mue_loader, ncci_loader


def _clear_all_caches():
    icd10_loader._clear_icd10_cache()
    mue_loader._clear_mue_cache()
    ncci_loader._clear_ncci_cache()


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
