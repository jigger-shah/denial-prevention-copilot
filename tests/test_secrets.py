"""
Tests for agents/secrets.py:get_secret() — session key (UI), local env var,
and Streamlit Cloud secrets resolution (Phase 10 deployment readiness +
session API key UI enhancement).

Resolution order under test: st.session_state, then OS env var, then
st.secrets, then default.
"""

from unittest.mock import MagicMock, patch

from agents.secrets import get_secret


def _mock_streamlit(session_value=None, secrets_value=None, secrets_raises=None):
    """Build a MagicMock standing in for the streamlit module, with
    session_state.get() and secrets.get() both explicitly configured —
    a bare MagicMock() is truthy by default and would otherwise look like
    a real value was found."""
    mock_st = MagicMock()
    mock_st.session_state.get.return_value = session_value
    if secrets_raises is not None:
        mock_st.secrets.get.side_effect = secrets_raises
    else:
        mock_st.secrets.get.return_value = secrets_value
    return mock_st


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
    mock_st = _mock_streamlit(secrets_value="secrets-value")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY") == "env-value"
    mock_st.secrets.get.assert_not_called()


def test_falls_back_to_streamlit_secrets_when_env_var_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = _mock_streamlit(secrets_value="secrets-value")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY") == "secrets-value"


def test_no_crash_when_streamlit_secrets_raises(monkeypatch):
    """st.secrets raises if no .streamlit/secrets.toml exists at all — the
    normal state for local development. This must never crash a local run
    that has no ANTHROPIC_API_KEY set either."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = _mock_streamlit(secrets_raises=Exception("no secrets.toml found"))
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY", "default") == "default"


def test_no_crash_when_streamlit_not_installed(monkeypatch):
    """Even if streamlit itself can't be imported in some context, get_secret
    must degrade to the default rather than raise."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch.dict("sys.modules", {"streamlit": None}):
        assert get_secret("ANTHROPIC_API_KEY", "default") == "default"


# ---------------------------------------------------------------------------
# Session API key (UI gear-icon popover)
# ---------------------------------------------------------------------------

def test_session_key_takes_precedence_over_env_and_secrets(monkeypatch):
    """A session key entered via the UI must win over both an app-owner env
    var and st.secrets — entering your own key for this browser session
    overrides whatever the app owner configured, for the rest of that session."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-value")
    mock_st = _mock_streamlit(session_value="session-value", secrets_value="secrets-value")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY") == "session-value"


def test_session_key_used_when_no_env_or_secrets(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = _mock_streamlit(session_value="session-value")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY") == "session-value"


def test_empty_session_value_falls_through_to_env(monkeypatch):
    """An empty/falsy session_state entry (e.g. the key was cleared) must not
    block the env var fallback — only a real, truthy session value wins."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-value")
    mock_st = _mock_streamlit(session_value="")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY") == "env-value"


def test_no_crash_when_session_state_raises(monkeypatch):
    """st.session_state raises outside a running Streamlit script (e.g. in a
    plain CLI run or certain test contexts) — get_secret must still resolve
    via env var/secrets, never crash."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-value")
    mock_st = MagicMock()
    mock_st.session_state.get.side_effect = Exception("no script run context")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert get_secret("ANTHROPIC_API_KEY") == "env-value"


def test_session_state_checked_with_same_secret_name(monkeypatch):
    """Sanity check on call shape: session_state.get() is queried with the
    same secret name passed to get_secret()."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = _mock_streamlit(session_value=None, secrets_value="secrets-value")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        get_secret("ANTHROPIC_API_KEY")
    mock_st.session_state.get.assert_called_with("ANTHROPIC_API_KEY")
