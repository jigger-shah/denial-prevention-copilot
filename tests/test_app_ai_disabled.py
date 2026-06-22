"""
Tests for app/main.py's AI-enabled/disabled UI behavior (v1.6 public release
hardening, closes TD-12).

Uses streamlit.testing.v1.AppTest to render the real app script. dotenv.load_dotenv
is mocked to a no-op so a real local .env (if present on the dev machine) can't
mask the "no key" path — these tests must hold true on a fresh public clone with
no .env file at all, not just in this dev environment.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


def _run_app():
    # default_timeout is a generous safety margin. The header's Data Source
    # status is now fully user-initiated (a "Check CMS Data Availability"
    # button inside the Data pill's popover) — app/main.py's header bar no
    # longer calls rules.data_source_status on page load at all, so the slow
    # first-real-parse cost this timeout originally existed for no longer
    # applies to a bare page render; left generous regardless as headroom.
    with patch("dotenv.load_dotenv", return_value=False):
        at = AppTest.from_file("app/main.py", default_timeout=150)
        at.run()
    return at


def test_app_launches_with_no_exception_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run_app()
    assert not at.exception


def test_header_shows_ai_disabled_pill_when_api_key_missing(monkeypatch):
    """v1.8a replaced the sidebar AI Agents box with a header pill. The
    session-API-key gear popover (Phase 13) replaced the old '.env' banner —
    the pill itself must still read exactly 'AI: Disabled', no other wording."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run_app()

    markdown_text = " ".join(el.value for el in at.markdown)
    assert "AI: Disabled" in markdown_text
    assert "AI: Enabled" not in markdown_text


def test_no_dotenv_instructions_anywhere_in_main_ui(monkeypatch):
    """The session API key UI (gear icon) replaced the old '.env'-instructing
    banner entirely — no main-UI text should tell a user to edit .env."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run_app()

    all_text = " ".join(el.value for el in at.markdown) + " ".join(el.value for el in at.caption)
    assert ".env" not in all_text


def test_header_does_not_show_ai_enabled_pill_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run_app()

    markdown_text = " ".join(el.value for el in at.markdown)
    assert "AI: Enabled" not in markdown_text


def test_header_shows_ai_enabled_pill_when_api_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = _run_app()

    markdown_text = " ".join(el.value for el in at.markdown)
    assert "AI: Enabled" in markdown_text
    assert "AI: Disabled" not in markdown_text


def test_deterministic_review_tab_renders_with_no_exception_when_api_key_missing(monkeypatch):
    """Sample/manual claim review tabs must render without the deterministic path breaking."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run_app()

    assert not at.exception
    assert any("Review Claim" in btn.label for btn in at.button)
