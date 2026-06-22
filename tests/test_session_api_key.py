"""
Tests for the session API key UI enhancement (gear-icon popover next to the
AI status pill, app/main.py + agents/secrets.py).

Behavioral coverage, at the orchestrator/agent boundary (no Streamlit runtime
needed for these — app/main.py's popover itself is exercised by the AppTest
smoke tests in tests/test_app_ai_disabled.py):
  - no key anywhere -> AI disabled, no Anthropic client constructed
  - env/secrets key -> AI enabled
  - session key -> AI enabled, even with no env/secrets key
  - clearing the session key -> disabled if no env/secrets key, still
    enabled if an env/secrets key exists (session key never deletes the
    app-owner key, it only ever shadows it while present)
  - a session key is never written to the audit trail

requests/anthropic clients are mocked throughout; no real API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.orchestrator import _ai_enabled


def _mock_streamlit(session_value=None):
    mock_st = MagicMock()
    mock_st.session_state.get.return_value = session_value
    mock_st.secrets.get.return_value = None
    return mock_st


# ---------------------------------------------------------------------------
# AI enabled/disabled resolution
# ---------------------------------------------------------------------------

def test_no_key_anywhere_means_ai_disabled(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = _mock_streamlit(session_value=None)
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert _ai_enabled() is False


def test_env_key_means_ai_enabled(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    mock_st = _mock_streamlit(session_value=None)
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert _ai_enabled() is True


def test_secrets_key_means_ai_enabled(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = MagicMock()
    mock_st.session_state.get.return_value = None
    mock_st.secrets.get.return_value = "secrets-key"
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert _ai_enabled() is True


def test_session_key_means_ai_enabled_with_no_env_or_secrets(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = _mock_streamlit(session_value="session-key")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert _ai_enabled() is True


def test_session_key_enables_ai_even_over_a_missing_app_key(monkeypatch):
    """The whole point of the feature: a visitor with no app-owner key
    configured can still enable AI for themselves for this session."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = _mock_streamlit(session_value="my-own-key")
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert _ai_enabled() is True


# ---------------------------------------------------------------------------
# Clearing the session key
# ---------------------------------------------------------------------------

def test_clearing_session_key_disables_ai_when_no_app_key_exists(monkeypatch):
    """Simulates app/main.py's 'Clear Key' button: st.session_state.pop(...)
    removes the entry, so session_state.get() reverts to None/falsy."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = _mock_streamlit(session_value=None)  # post-clear state
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert _ai_enabled() is False


def test_clearing_session_key_leaves_ai_enabled_when_app_key_exists(monkeypatch):
    """Clearing a session key must never remove or disable an app-owner
    env/secrets key — it only ever shadowed it while present."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "app-owner-key")
    mock_st = _mock_streamlit(session_value=None)  # post-clear state
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        assert _ai_enabled() is True


# ---------------------------------------------------------------------------
# No Anthropic client constructed when no key exists
# ---------------------------------------------------------------------------

def test_no_anthropic_client_constructed_when_no_key_anywhere(monkeypatch):
    """validate_coverage()/validate_coding() must never construct an
    anthropic.Anthropic client when get_secret() resolves to nothing at all
    (no session key, no env var, no secrets)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_st = _mock_streamlit(session_value=None)

    from agents.coverage_validation import validate_coverage
    from agents.coding_validation import validate_coding
    from rules.models import ClaimIn

    claim = ClaimIn(
        claim_id="CLM-SESSION-KEY-001", payer="Medicare", npi="",
        cpt_codes=["99213"], icd10_codes=["Z00.00"], modifiers=[],
        place_of_service="11", units={},
    )

    with patch.dict("sys.modules", {"streamlit": mock_st}), \
         patch("agents.coverage_validation.anthropic.Anthropic") as mock_cov_client, \
         patch("agents.coding_validation.anthropic.Anthropic") as mock_coding_client:
        cov_findings, _ = validate_coverage(claim)
        coding_findings, _ = validate_coding(claim)

    assert cov_findings == []
    assert coding_findings == []
    mock_cov_client.assert_not_called()
    mock_coding_client.assert_not_called()


# ---------------------------------------------------------------------------
# Session key is never persisted to the audit trail
# ---------------------------------------------------------------------------

def test_session_key_never_appears_in_a_saved_audit_decision(monkeypatch, tmp_path):
    """A session key set in st.session_state must never leak into any field
    of a saved AuditDecision — the audit repository has no key-related
    column at all, and nothing in the save path ever reads session_state."""
    from db.audit_repository import AuditDecision, AuditRepository

    secret_value = "sk-ant-totally-secret-session-key-do-not-persist"
    mock_st = _mock_streamlit(session_value=secret_value)

    repo = AuditRepository(db_path=tmp_path / "session_key_audit_test.db")
    repo.initialize_database()

    decision = AuditDecision(
        claim_id="CLM-SESSION-KEY-002",
        finding_id="abc123def456",
        source="rule_layer",
        severity="HIGH",
        issue="Bundled code pair",
        recommendation="Remove the bundled code.",
        citation_source="NCCI PTP",
        citation_doc_id="NCCI-PTP-SYNTHETIC",
        citation_section="Column 1 / Column 2",
        citation_edition="synthetic sample",
        confidence=0.95,
        user_decision="accepted",
        override_reason="",
        reviewer_name="Dr. Test",
        model_version="rule_layer_v0.1",
        prompt_version="n/a",
    )

    with patch.dict("sys.modules", {"streamlit": mock_st}):
        repo.save_decision(decision)
        rows = repo.get_decisions(claim_id="CLM-SESSION-KEY-002")

    assert len(rows) == 1
    row = rows[0]
    assert secret_value not in str(row.values())
    assert "ANTHROPIC_API_KEY" not in row
    # Structural guarantee: the dataclass and DB schema have no key-shaped field at all.
    assert not any("key" in field.lower() for field in row)
