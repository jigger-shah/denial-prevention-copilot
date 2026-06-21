"""
Tests for agents/secrets.py:get_secret() — local env var vs Streamlit Cloud
secrets resolution (Phase 10 — Streamlit Cloud deployment readiness).
"""

from unittest.mock import MagicMock, patch

from agents.secrets import get_secret


def test_returns_env_var_when_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-value")
    assert get_secret("ANTHROPIC_API_KEY") == "env-value"


def test_returns_default_when_nothing_set(monkeypatch):
    monkeypatch.delenv("SOME_UNSET_SECRET", raising=False)
    assert get_secret("SOME_UNSET_SECRET", "fallback") == "fallback"


def test_returns_empty_default_when_nothing_set_and_no_default_given(monkeypatch):
    monkeypatch.delenv("SOME_UNSET_SECRET", raising=False)
    assert get_secret("SOME_UNSET_SECRET") == ""


def test_env_var_takes_precedence_over_streamlit_secrets(monkeypatch):
    """Local .env / env var must win even if st.secrets also has a value —
    local developer behavior must not change just because secrets.toml exists."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-value")
    mock_st = MagicMock()
    mock_st.secrets.get.return_value = "secrets-value"
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY") == "env-value"
    mock_st.secrets.get.assert_not_called()


def test_falls_back_to_streamlit_secrets_when_env_var_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = MagicMock()
    mock_st.secrets.get.return_value = "secrets-value"
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY") == "secrets-value"


def test_no_crash_when_streamlit_secrets_raises(monkeypatch):
    """st.secrets raises if no .streamlit/secrets.toml exists at all — the
    normal state for local development. This must never crash a local run
    that has no ANTHROPIC_API_KEY set either."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = MagicMock()
    mock_st.secrets.get.side_effect = Exception("no secrets.toml found")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY", "default") == "default"


def test_no_crash_when_streamlit_not_installed(monkeypatch):
    """Even if streamlit itself can't be imported in some context, get_secret
    must degrade to the default rather than raise."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch.dict("sys.modules", {"streamlit": None}):
        assert get_secret("ANTHROPIC_API_KEY", "default") == "default"
