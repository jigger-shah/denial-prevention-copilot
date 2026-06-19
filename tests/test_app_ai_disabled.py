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
    with patch("dotenv.load_dotenv", return_value=False):
        at = AppTest.from_file("app/main.py")
        at.run()
    return at


def test_app_launches_with_no_exception_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run_app()
    assert not at.exception


def test_sidebar_shows_ai_disabled_warning_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run_app()

    warnings = " ".join(el.value for el in at.sidebar.warning)
    assert "AI Agents Disabled" in warnings
    assert "ANTHROPIC_API_KEY" in warnings
    assert "Deterministic rule-engine review remains available" in warnings


def test_sidebar_does_not_show_ai_enabled_success_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run_app()

    successes = " ".join(el.value for el in at.sidebar.success)
    assert "AI enabled" not in successes


def test_sidebar_shows_ai_enabled_when_api_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = _run_app()

    successes = " ".join(el.value for el in at.sidebar.success)
    assert "AI enabled" in successes
    warnings = " ".join(el.value for el in at.sidebar.warning)
    assert "AI Agents Disabled" not in warnings


def test_deterministic_review_tab_renders_with_no_exception_when_api_key_missing(monkeypatch):
    """Sample/manual claim review tabs must render without the deterministic path breaking."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run_app()

    assert not at.exception
    assert any("Review Claim" in btn.label for btn in at.button)
