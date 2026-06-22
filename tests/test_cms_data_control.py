"""
Tests for the CMS Data Control UI (Phase 13 follow-up) — the Data pill's
status check is now fully user-initiated, mirroring the gear-icon session
API key control: no automatic check, no automatic download, no automatic
rerun on page load. rules.data_source_status is only computed when the user
clicks "Check CMS Data Availability" (or later, "Refresh Data Status")
inside the Data pill's popover.

No real network calls; no real Anthropic calls. Uses streamlit.testing.v1.AppTest
to render the real app script, same convention as tests/test_app_ai_disabled.py
and tests/test_session_api_key.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


def _run_app():
    with patch("dotenv.load_dotenv", return_value=False):
        at = AppTest.from_file("app/main.py", default_timeout=150)
        at.run()
    return at


# ---------------------------------------------------------------------------
# Default state — nothing computed, nothing downloaded, no rerun
# ---------------------------------------------------------------------------

def test_app_loads_without_calling_data_source_summary(monkeypatch):
    """The header must never call _data_source_summary() on a bare page load."""
    with patch("app.main._data_source_summary") as mock_summary:
        at = _run_app()

    assert not at.exception
    mock_summary.assert_not_called()


def test_no_rerun_triggered_on_startup():
    """st.rerun() must never fire just from rendering the header — only from
    an explicit user action (the check/refresh buttons)."""
    with patch("streamlit.rerun") as mock_rerun:
        at = _run_app()

    assert not at.exception
    mock_rerun.assert_not_called()


def test_data_pill_defaults_to_not_refreshed():
    """Before any check, the popover must offer 'Check CMS Data Availability'
    and must not yet offer 'Refresh Data Status' (that only appears once a
    result exists)."""
    at = _run_app()

    assert any(b.key == "check_cms_data_btn" for b in at.button)
    assert not any(b.key == "refresh_cms_data_btn" for b in at.button)


def test_data_source_ready_not_set_by_default():
    at = _run_app()
    assert "_data_source_ready" not in at.session_state


def test_no_cms_asset_download_attempted_on_load(monkeypatch):
    """No CMS_* URL configured or not, the download/discovery machinery must
    never even be touched until the user clicks the check button."""
    monkeypatch.setenv("CMS_NCCI_F1_URL", "https://example.invalid/f1.xlsx")
    with patch("rules.cms_asset_fetch.requests.get") as mock_get:
        at = _run_app()

    assert not at.exception
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Clicking "Check CMS Data Availability" resolves status
# ---------------------------------------------------------------------------

def test_clicking_check_button_resolves_status():
    at = _run_app()
    at.button(key="check_cms_data_btn").click().run()

    assert not at.exception
    assert at.session_state["_data_source_ready"] is True
    assert "overall" in at.session_state["_data_source_summary_cache"]
    # The popover now offers Refresh instead of Check.
    assert any(b.key == "refresh_cms_data_btn" for b in at.button)
    assert not any(b.key == "check_cms_data_btn" for b in at.button)


def test_resolved_status_persists_across_subsequent_reruns():
    """Once checked, the app must not re-check automatically on a later,
    unrelated rerun (e.g. typing in the reviewer field)."""
    at = _run_app()
    at.button(key="check_cms_data_btn").click().run()
    assert at.session_state["_data_source_ready"] is True

    with patch("app.main._data_source_summary") as mock_summary:
        at.text_input(key="reviewer_name").set_value("Dr. Test").run()

    assert not at.exception
    assert at.session_state["_data_source_ready"] is True
    mock_summary.assert_not_called()


# ---------------------------------------------------------------------------
# Refresh re-checks and clears the deeper per-loader caches
# ---------------------------------------------------------------------------

def test_refresh_button_recomputes_status():
    at = _run_app()
    at.button(key="check_cms_data_btn").click().run()
    at.button(key="refresh_cms_data_btn").click().run()

    assert not at.exception
    assert at.session_state["_data_source_ready"] is True
    assert any(b.key == "refresh_cms_data_btn" for b in at.button)


def test_refresh_clears_underlying_loader_caches():
    """Refresh must clear the deeper per-loader/per-asset caches too, not
    just this function's own cache_resource — otherwise a refresh after
    updating secrets or deploying new CMS assets would silently do nothing."""
    at = _run_app()
    at.button(key="check_cms_data_btn").click().run()

    with patch("rules.ncci_loader._clear_ncci_cache") as mock_ncci, \
         patch("rules.mue_loader._clear_mue_cache") as mock_mue, \
         patch("rules.icd10_loader._clear_icd10_cache") as mock_icd10, \
         patch("rules.cms_asset_fetch._clear_cms_asset_cache") as mock_cms:
        at.button(key="refresh_cms_data_btn").click().run()

    assert not at.exception
    mock_ncci.assert_called_once()
    mock_mue.assert_called_once()
    mock_icd10.assert_called_once()
    mock_cms.assert_called_once()


# ---------------------------------------------------------------------------
# No regression to the AI key gear control
# ---------------------------------------------------------------------------

def test_ai_key_gear_controls_unaffected_by_default_cms_state():
    at = _run_app()
    assert any(w.key == "session_api_key_input" for w in at.text_input)
    assert any(b.key == "enable_session_api_key_btn" for b in at.button)
    assert any(b.key == "clear_session_api_key_btn" for b in at.button)


def test_ai_key_gear_controls_unaffected_after_cms_check():
    at = _run_app()
    at.button(key="check_cms_data_btn").click().run()

    assert any(w.key == "session_api_key_input" for w in at.text_input)
    assert any(b.key == "enable_session_api_key_btn" for b in at.button)
    assert any(b.key == "clear_session_api_key_btn" for b in at.button)
