"""
Tests for app/main.py's cached AI demo artifacts (v1.6 public release hardening).

When ANTHROPIC_API_KEY is absent, designated sample claims show pre-generated
AI findings (data/synthetic/cached_ai_demo_artifacts.json) so public users can
preview representative agent output without a live API call. These tests cover
the data-loading and lookup logic directly; full button-click UI flows are
exercised manually (streamlit.testing.v1.AppTest's widget-interaction simulator
has a pre-existing timeout on this app's "Run Full Review" rerun, unrelated to
this feature — see tests/test_app_ai_disabled.py for the AppTest coverage that
does work, which checks initial-render state only).
"""

from __future__ import annotations

from unittest.mock import patch

from app.main import load_cached_ai_demo_artifacts, _cached_ai_findings_for
from rules.models import Citation, Finding


def test_cached_artifacts_file_loads():
    artifacts = load_cached_ai_demo_artifacts()
    assert "CLM-001" in artifacts
    assert "CLM-002" in artifacts
    assert "CLM-005" in artifacts


def test_cached_ai_findings_for_returns_findings_for_designated_claims():
    for claim_id in ("CLM-001", "CLM-002", "CLM-005"):
        findings = _cached_ai_findings_for(claim_id)
        assert findings
        assert all(isinstance(f, Finding) for f in findings)
        assert all(isinstance(f.citation, Citation) for f in findings)
        assert all(f.source == "agent_layer" for f in findings)


def test_cached_ai_findings_for_returns_none_for_claim_without_cached_artifact():
    assert _cached_ai_findings_for("CLM-003") is None
    assert _cached_ai_findings_for("CLM-004") is None
    assert _cached_ai_findings_for("CLM-NONEXISTENT") is None


def test_multi_finding_scenario_includes_both_coverage_and_coding():
    findings = _cached_ai_findings_for("CLM-001")
    rules_seen = {f.rule for f in findings}
    assert "coverage_validation" in rules_seen
    assert "coding_validation" in rules_seen


def test_coding_finding_scenario_has_only_coding_finding():
    findings = _cached_ai_findings_for("CLM-002")
    assert all(f.rule == "coding_validation" for f in findings)


def test_coverage_finding_scenario_includes_coverage_finding():
    findings = _cached_ai_findings_for("CLM-005")
    assert any(f.rule == "coverage_validation" for f in findings)


def test_cached_findings_carry_required_citation_fields():
    """No citation -> no finding applies to cached artifacts too."""
    for claim_id in ("CLM-001", "CLM-002", "CLM-005"):
        for finding in _cached_ai_findings_for(claim_id):
            assert finding.citation.source
            assert finding.citation.doc_id


def test_render_cached_ai_demo_is_noop_when_ai_enabled(monkeypatch):
    """Live agents always take priority — cached artifacts must never render when a key is present."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "_AI_ENABLED", True)
    with patch("streamlit.divider") as mock_divider, patch("streamlit.info") as mock_info:
        main_module._render_cached_ai_demo("CLM-001")
        mock_divider.assert_not_called()
        mock_info.assert_not_called()


def test_render_cached_ai_demo_is_noop_for_claim_with_no_cached_artifact(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_AI_ENABLED", False)
    with patch("streamlit.divider") as mock_divider, patch("streamlit.info") as mock_info:
        main_module._render_cached_ai_demo("CLM-003")
        mock_divider.assert_not_called()
        mock_info.assert_not_called()
