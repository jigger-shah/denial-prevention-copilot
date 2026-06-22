"""
Tests for rules/cms_asset_fetch.py — optional CMS reference asset auto-download
from GitHub Release Assets (Phase 11).

No real network calls. requests.get is patched per the same convention used
elsewhere in this suite (tests/test_rules.py for NPPES, tests/test_ingest.py
for the CMS Coverage API). Every test isolates the cache root under tmp_path
so nothing here ever touches the real OS temp dir or a real download.
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from rules import cms_asset_fetch


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Every test gets its own cache root and a clean ensure_*_assets() memoization."""
    monkeypatch.setattr(cms_asset_fetch, "_CACHE_ROOT", tmp_path / "cms_cache")
    cms_asset_fetch._clear_cms_asset_cache()
    yield
    cms_asset_fetch._clear_cms_asset_cache()


@pytest.fixture(autouse=True)
def _no_real_config(monkeypatch):
    """Clear every CMS asset env var so a developer's local environment can
    never accidentally configure a real download in this suite."""
    for name in (
        "CMS_NCCI_F1_URL", "CMS_NCCI_F2_URL", "CMS_NCCI_F3_URL", "CMS_NCCI_F4_URL",
        "CMS_MUE_URL", "CMS_ICD10_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _mock_ok_response(content: bytes = b"fake xlsx bytes"):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.iter_content.return_value = [content]
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


# ---------------------------------------------------------------------------
# No URLs configured
# ---------------------------------------------------------------------------

def test_no_urls_configured_skips_download_entirely():
    with patch("rules.cms_asset_fetch.requests.get") as mock_get:
        result = cms_asset_fetch.ensure_ncci_assets()

    mock_get.assert_not_called()
    assert result == {"attempted": False, "succeeded": [], "errors": {}}


def test_no_urls_configured_mue_and_icd10_also_skip():
    with patch("rules.cms_asset_fetch.requests.get") as mock_get:
        mue_result = cms_asset_fetch.ensure_mue_assets()
        icd10_result = cms_asset_fetch.ensure_icd10_assets()

    mock_get.assert_not_called()
    assert mue_result["attempted"] is False
    assert icd10_result["attempted"] is False


# ---------------------------------------------------------------------------
# Download success
# ---------------------------------------------------------------------------

def test_download_success_writes_file_to_cache(monkeypatch):
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")

    with patch("rules.cms_asset_fetch.requests.get", return_value=_mock_ok_response()):
        result = cms_asset_fetch.ensure_mue_assets()

    assert result["attempted"] is True
    assert result["succeeded"] == ["mue_practitioner.xlsx"]
    assert result["errors"] == {}
    cached_file = pathlib.Path(cms_asset_fetch.mue_cache_dir()) / "mue_practitioner.xlsx"
    assert cached_file.exists()
    assert cached_file.read_bytes() == b"fake xlsx bytes"


def test_download_success_for_all_four_ncci_files(monkeypatch):
    for i in range(1, 5):
        monkeypatch.setenv(f"CMS_NCCI_F{i}_URL", f"https://example.invalid/f{i}.xlsx")

    with patch("rules.cms_asset_fetch.requests.get", return_value=_mock_ok_response()):
        result = cms_asset_fetch.ensure_ncci_assets()

    assert result["attempted"] is True
    assert sorted(result["succeeded"]) == sorted(
        ["ccipra_f1.xlsx", "ccipra_f2.xlsx", "ccipra_f3.xlsx", "ccipra_f4.xlsx"]
    )
    assert list(pathlib.Path(cms_asset_fetch.ncci_cache_dir()).glob("*.xlsx"))


# ---------------------------------------------------------------------------
# Download failure
# ---------------------------------------------------------------------------

def test_download_failure_is_graceful_no_exception(monkeypatch):
    monkeypatch.setenv("CMS_ICD10_URL", "https://example.invalid/icd10.txt")

    with patch("rules.cms_asset_fetch.requests.get", side_effect=ConnectionError("network down")):
        result = cms_asset_fetch.ensure_icd10_assets()  # must not raise

    assert result["attempted"] is True
    assert result["succeeded"] == []
    assert "CMS_ICD10_URL" in result["errors"]
    assert "network down" in result["errors"]["CMS_ICD10_URL"]
    cached_file = pathlib.Path(cms_asset_fetch.icd10_cache_dir()) / "icd10cm_order_downloaded.txt"
    assert not cached_file.exists()


def test_download_timeout_is_graceful(monkeypatch):
    import requests as real_requests
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")

    with patch("rules.cms_asset_fetch.requests.get", side_effect=real_requests.exceptions.Timeout("timed out")):
        result = cms_asset_fetch.ensure_mue_assets()

    assert result["succeeded"] == []
    assert "timed out" in result["errors"]["CMS_MUE_URL"]


def test_download_http_error_is_graceful(monkeypatch):
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")

    resp = MagicMock()
    resp.raise_for_status.side_effect = Exception("404 Not Found")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False

    with patch("rules.cms_asset_fetch.requests.get", return_value=resp):
        result = cms_asset_fetch.ensure_mue_assets()

    assert result["succeeded"] == []
    assert "404" in result["errors"]["CMS_MUE_URL"]


# ---------------------------------------------------------------------------
# Partial download
# ---------------------------------------------------------------------------

def test_partial_ncci_download_some_succeed_some_fail(monkeypatch):
    monkeypatch.setenv("CMS_NCCI_F1_URL", "https://example.invalid/f1.xlsx")
    monkeypatch.setenv("CMS_NCCI_F2_URL", "https://example.invalid/f2.xlsx")
    # F3/F4 left unconfigured — simulates "maintainer only uploaded some assets"

    with patch("rules.cms_asset_fetch.requests.get", return_value=_mock_ok_response()):
        result = cms_asset_fetch.ensure_ncci_assets()

    assert sorted(result["succeeded"]) == ["ccipra_f1.xlsx", "ccipra_f2.xlsx"]
    assert result["errors"] == {}


def test_partial_ncci_download_one_url_fails(monkeypatch):
    monkeypatch.setenv("CMS_NCCI_F1_URL", "https://example.invalid/f1.xlsx")
    monkeypatch.setenv("CMS_NCCI_F2_URL", "https://example.invalid/f2.xlsx")

    def _side_effect(url, **kwargs):
        if "f2" in url:
            raise ConnectionError("f2 unreachable")
        return _mock_ok_response()

    with patch("rules.cms_asset_fetch.requests.get", side_effect=_side_effect):
        result = cms_asset_fetch.ensure_ncci_assets()

    assert result["succeeded"] == ["ccipra_f1.xlsx"]
    assert "CMS_NCCI_F2_URL" in result["errors"]


# ---------------------------------------------------------------------------
# Cached file reused — no re-download
# ---------------------------------------------------------------------------

def test_already_cached_file_is_not_redownloaded(monkeypatch):
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")
    cache_dir = pathlib.Path(cms_asset_fetch.mue_cache_dir())
    cache_dir.mkdir(parents=True)
    (cache_dir / "mue_practitioner.xlsx").write_bytes(b"already here")

    with patch("rules.cms_asset_fetch.requests.get") as mock_get:
        result = cms_asset_fetch.ensure_mue_assets()

    mock_get.assert_not_called()
    assert result["succeeded"] == ["mue_practitioner.xlsx"]
    assert (cache_dir / "mue_practitioner.xlsx").read_bytes() == b"already here"


def test_ensure_is_memoized_within_a_process(monkeypatch):
    """A second call within the same process must not re-attempt the download,
    even on failure — matches the 'no repeated downloads' / 'attempted at most
    once per process' design (same philosophy as the existing lru_cache'd
    NCCI/MUE/ICD10 tables themselves)."""
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")

    with patch("rules.cms_asset_fetch.requests.get", side_effect=ConnectionError("down")) as mock_get:
        cms_asset_fetch.ensure_mue_assets()
        cms_asset_fetch.ensure_mue_assets()  # second call, same process, no _clear_cms_asset_cache()

    assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# Zero-byte file rejected
# ---------------------------------------------------------------------------

def test_zero_byte_download_is_rejected(monkeypatch):
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")

    with patch("rules.cms_asset_fetch.requests.get", return_value=_mock_ok_response(content=b"")):
        result = cms_asset_fetch.ensure_mue_assets()

    assert result["succeeded"] == []
    assert "empty" in result["errors"]["CMS_MUE_URL"]
    cached_file = pathlib.Path(cms_asset_fetch.mue_cache_dir()) / "mue_practitioner.xlsx"
    assert not cached_file.exists()


# ---------------------------------------------------------------------------
# Atomic write behavior
# ---------------------------------------------------------------------------

def test_successful_download_leaves_no_part_file(monkeypatch):
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")

    with patch("rules.cms_asset_fetch.requests.get", return_value=_mock_ok_response()):
        cms_asset_fetch.ensure_mue_assets()

    cache_dir = pathlib.Path(cms_asset_fetch.mue_cache_dir())
    assert not list(cache_dir.glob("*.part"))
    assert (cache_dir / "mue_practitioner.xlsx").exists()


def test_failed_download_leaves_no_part_file_and_no_dest_file(monkeypatch):
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")

    with patch("rules.cms_asset_fetch.requests.get", side_effect=ConnectionError("down")):
        cms_asset_fetch.ensure_mue_assets()

    cache_dir = pathlib.Path(cms_asset_fetch.mue_cache_dir())
    assert not list(cache_dir.glob("*.part"))
    assert not (cache_dir / "mue_practitioner.xlsx").exists()


def test_failed_download_does_not_clobber_existing_valid_cache(monkeypatch):
    """A failed re-attempt must never overwrite an already-good cached file —
    in practice this can't even be reached today since an existing valid file
    short-circuits before any network call, but this locks in that invariant
    directly against _download_to_cache()."""
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")
    cache_dir = pathlib.Path(cms_asset_fetch.mue_cache_dir())
    cache_dir.mkdir(parents=True)
    dest = cache_dir / "mue_practitioner.xlsx"
    dest.write_bytes(b"good existing content")

    with patch("rules.cms_asset_fetch.requests.get", side_effect=ConnectionError("down")):
        ok, error = cms_asset_fetch._download_to_cache("https://example.invalid/mue.xlsx", dest)

    assert ok is False
    assert dest.read_bytes() == b"good existing content"


# ---------------------------------------------------------------------------
# Loader discovers cached files (rules/{ncci,mue,icd10}_loader.py integration)
# ---------------------------------------------------------------------------

def test_ncci_loader_discovers_downloaded_files(monkeypatch):
    from rules import ncci_loader
    ncci_loader._clear_ncci_cache()
    monkeypatch.setenv("CMS_NCCI_F1_URL", "https://example.invalid/f1.xlsx")

    with patch("rules.cms_asset_fetch.requests.get", return_value=_mock_ok_response()):
        files = ncci_loader.discover_ncci_files()  # reference_dir=None — the production default

    assert len(files) == 1
    assert "ccipra_f1.xlsx" in files[0]
    ncci_loader._clear_ncci_cache()


def test_mue_loader_discovers_downloaded_files(monkeypatch):
    from rules import mue_loader
    mue_loader._clear_mue_cache()
    monkeypatch.setenv("CMS_MUE_URL", "https://example.invalid/mue.xlsx")

    with patch("rules.cms_asset_fetch.requests.get", return_value=_mock_ok_response()):
        files = mue_loader.discover_mue_files()

    assert len(files) == 1
    mue_loader._clear_mue_cache()


def test_icd10_loader_discovers_downloaded_file(monkeypatch):
    from rules import icd10_loader
    icd10_loader._clear_icd10_cache()
    monkeypatch.setenv("CMS_ICD10_URL", "https://example.invalid/icd10.txt")

    with patch("rules.cms_asset_fetch.requests.get", return_value=_mock_ok_response()):
        fpath = icd10_loader.discover_icd10_file()

    assert fpath is not None
    assert "icd10cm_order" in fpath
    icd10_loader._clear_icd10_cache()


def test_loader_explicit_reference_dir_override_bypasses_download(tmp_path, monkeypatch):
    """An explicit reference_dir (as every pre-existing test in this suite
    uses) must never trigger a download attempt — only the reference_dir=None
    default path does."""
    from rules import ncci_loader
    ncci_loader._clear_ncci_cache()
    monkeypatch.setenv("CMS_NCCI_F1_URL", "https://example.invalid/f1.xlsx")

    with patch("rules.cms_asset_fetch.requests.get") as mock_get:
        files = ncci_loader.discover_ncci_files(reference_dir=str(tmp_path))

    mock_get.assert_not_called()
    assert files == []
    ncci_loader._clear_ncci_cache()


# ---------------------------------------------------------------------------
# Streamlit app boot path
# ---------------------------------------------------------------------------

def _run_app():
    from streamlit.testing.v1 import AppTest
    with patch("dotenv.load_dotenv", return_value=False):
        at = AppTest.from_file("app/main.py", default_timeout=150)
        at.run()
    return at


def test_app_boots_with_no_cms_urls_configured(monkeypatch):
    """No CMS_* env vars set (the default, e.g. a fresh clone) — app must boot
    with no exception, exactly as before this feature existed."""
    for name in (
        "CMS_NCCI_F1_URL", "CMS_NCCI_F2_URL", "CMS_NCCI_F3_URL", "CMS_NCCI_F4_URL",
        "CMS_MUE_URL", "CMS_ICD10_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    at = _run_app()
    assert not at.exception


def test_app_boots_with_invalid_cms_urls_configured(monkeypatch):
    """Configured-but-unreachable URLs must never block app boot — the
    download attempt happens lazily on first data_source_status access, and
    any failure there must degrade gracefully, not crash page render. The
    network call itself is mocked to fail deterministically (no real network
    access, no DNS dependency, no flakiness) — this test is about app boot
    behavior on failure, not about exercising a real network timeout."""
    monkeypatch.setenv("CMS_NCCI_F1_URL", "https://example.invalid/does-not-exist.xlsx")
    monkeypatch.setenv("CMS_MUE_URL", "not-even-a-valid-url")

    with patch("rules.cms_asset_fetch.requests.get", side_effect=ConnectionError("simulated unreachable")):
        at = _run_app()

    assert not at.exception
