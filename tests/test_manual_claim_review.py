"""
Tests for the manual-claim AI execution path (fix: manual claims must run the
same full review pipeline — rule layer + Coverage Agent + Coding Agent +
synthesis — as demo claims, not a degraded or cached-demo path).

These tests cover:
  - build_manual_claim() normalization produces a ClaimIn-compatible dict
    with the same shape demo claims use (already covered in detail by
    tests/test_claim_intake.py; this file adds the orchestrator-level and
    UI-level checks that were missing).
  - agents.orchestrator.run_review() is invoked identically for a manually-
    built claim as for a demo claim — same call, same agents, same synthesis.
  - Manual claims never reach app/main.py's cached-demo-artifact helpers.
  - Manual claims still work end-to-end with no ANTHROPIC_API_KEY (rule
    layer only) and with no ChromaDB/CMS corpus available (JSON fallback).
  - Audit trail accepts a manual-style claim_id like any other.
  - A Streamlit smoke render of "Enter manually" mode raises no exception
    (no button click — see tests/test_cached_ai_demo.py's docstring for why
    AppTest's "Run Full Review" click path isn't exercised here).

No real Anthropic API calls. No real ChromaDB index. No real NPPES network
calls (NPI left blank in these claims, which check_npi() treats as omitted).
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

from agents.orchestrator import run_review
from app.claim_intake import build_manual_claim
from db.audit_repository import AuditDecision, AuditRepository
from rules.models import Citation, ClaimIn, Finding
from rules.rule_engine import CHECKS_RUN, load_claim


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _api_key_present(monkeypatch):
    """Most tests here mock validate_coverage/validate_coding directly and
    expect run_review() to call them — same convention as test_orchestrator.py.
    Tests for the no-key path explicitly delenv instead."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def _manual_claim_dict(
    claim_id="CLM-MANUAL-TEST-001",
    cpt_lines=None,
    icd10_codes=None,
):
    """Build a manual claim_dict via the real UI-facing builder, not a hand-rolled dict."""
    header = {
        "claim_id": claim_id,
        "payer_name": "Medicare",
        "payer_id": "",
        "npi": "",
        "provider_specialty": "",
        "note_text": "",
    }
    icd10_codes = icd10_codes or ["Z00.00"]
    lines = cpt_lines or [
        {"cpt": "99213", "mod1": "", "mod2": "", "units": 1,
         "icd10_1": icd10_codes[0], "icd10_2": "", "icd10_3": "", "icd10_4": ""},
    ]
    return build_manual_claim(header, lines)


def _coverage_finding():
    return Finding(
        rule="coverage_validation",
        severity="MEDIUM",
        issue="Coverage concern",
        recommendation="Review documentation.",
        citation=Citation(source="coverage_validation", doc_id="LCD_TEST", section="Indications", edition=""),
        confidence=0.85,
        source="agent_layer",
    )


def _coding_finding():
    return Finding(
        rule="coding_validation",
        severity="MEDIUM",
        issue="Coding concern",
        recommendation="Use a more specific code.",
        citation=Citation(source="coding_validation", doc_id="LCD_TEST", section="Indications", edition=""),
        confidence=0.85,
        source="agent_layer",
    )


# ---------------------------------------------------------------------------
# Manual claim normalization (acceptance criteria #1-#3 substrate)
# ---------------------------------------------------------------------------

def test_manual_claim_normalizes_into_same_schema_as_demo_claim():
    """A manual claim_dict, once run through load_claim(), must produce a
    ClaimIn with the same field set demo claims use — no special-casing."""
    demo_dict = {
        "claim_id": "CLM-DEMO-001",
        "payer": "Medicare",
        "npi": "",
        "cpt_codes": ["99213"],
        "icd10_codes": ["Z00.00"],
        "modifiers": [],
        "place_of_service": "11",
        "units": {"99213": 1},
    }
    manual_dict = _manual_claim_dict()

    demo_claim = load_claim(demo_dict)
    manual_claim = load_claim(manual_dict)

    assert isinstance(demo_claim, ClaimIn)
    assert isinstance(manual_claim, ClaimIn)
    # Same dataclass, same fields populated (claim_id/payer differ by design; the
    # structural shape — which fields exist and are non-None-typed — must match).
    assert set(vars(demo_claim)) == set(vars(manual_claim))
    assert manual_claim.cpt_codes == ["99213"]
    assert manual_claim.icd10_codes == ["Z00.00"]
    assert manual_claim.payer == "Medicare"


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_manual_claim_with_ncci_pair_triggers_deterministic_bundling_finding(mock_coverage, mock_coding):
    """Acceptance criterion #1: CPT 80053 + 80048 manually entered must trigger NCCI.
    Agents mocked here since this test is only about the deterministic rule layer."""
    mock_coverage.return_value = ([], [])
    mock_coding.return_value = ([], [])

    claim_dict = _manual_claim_dict(cpt_lines=[
        {"cpt": "80053", "mod1": "", "mod2": "", "units": 1,
         "icd10_1": "Z00.00", "icd10_2": "", "icd10_3": "", "icd10_4": ""},
        {"cpt": "80048", "mod1": "", "mod2": "", "units": 1,
         "icd10_1": "", "icd10_2": "", "icd10_3": "", "icd10_4": ""},
    ])
    claim = load_claim(claim_dict)
    assessment, _ = run_review(claim)

    assert any(f.rule == "ncci_ptp" for f in assessment.findings)


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_manual_claim_with_unit_overage_triggers_deterministic_mue_finding(mock_coverage, mock_coding):
    """Acceptance criterion #2: a manually entered CPT exceeding its MUE limit
    (80053 has mue_value=1 in the real CMS table) must trigger a MUE finding."""
    mock_coverage.return_value = ([], [])
    mock_coding.return_value = ([], [])

    claim_dict = _manual_claim_dict(cpt_lines=[
        {"cpt": "80053", "mod1": "", "mod2": "", "units": 3,
         "icd10_1": "", "icd10_2": "", "icd10_3": "", "icd10_4": ""},
    ])
    claim = load_claim(claim_dict)
    assessment, _ = run_review(claim)

    assert any(f.rule == "mue_unit_limit" for f in assessment.findings)


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_manual_claim_with_icd_cpt_mismatch_triggers_coding_review(mock_coverage, mock_coding):
    """Acceptance criterion #3: Z00.00 (preventive) billed with a problem-
    oriented E/M (99214) must trigger the deterministic dx_procedure_conflict
    coding check, manually entered exactly as the rule-engine tests cover it
    for sample claims."""
    mock_coverage.return_value = ([], [])
    mock_coding.return_value = ([], [])

    claim_dict = _manual_claim_dict(
        cpt_lines=[{"cpt": "99214", "mod1": "", "mod2": "", "units": 1,
                    "icd10_1": "Z00.00", "icd10_2": "", "icd10_3": "", "icd10_4": ""}],
        icd10_codes=["Z00.00"],
    )
    claim = load_claim(claim_dict)
    assessment, _ = run_review(claim)

    assert any(f.rule == "dx_procedure_conflict" and f.severity == "HIGH" for f in assessment.findings)


# ---------------------------------------------------------------------------
# Manual claim invokes the same orchestrator pipeline as a demo claim
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_manual_claim_invokes_coverage_and_coding_agents_like_demo_claim(mock_coverage, mock_coding):
    """A manually-built claim must reach both live agents exactly like a demo
    claim does — same orchestrator call, no manual-claim-specific branching."""
    mock_coverage.return_value = ([_coverage_finding()], [{"document_id": "LCD_TEST"}])
    mock_coding.return_value = ([_coding_finding()], [{"document_id": "LCD_TEST"}])

    claim_dict = _manual_claim_dict()
    claim = load_claim(claim_dict)
    assessment, retrieved_policies = run_review(claim)

    mock_coverage.assert_called_once()
    mock_coding.assert_called_once()
    assert mock_coverage.call_args[0][0] is claim
    assert mock_coding.call_args[0][0] is claim
    assert any(f.rule == "coverage_validation" for f in assessment.findings)
    assert any(f.rule == "coding_validation" for f in assessment.findings)
    assert assessment.checks_run == [
        *CHECKS_RUN,
        "Coverage validation — LLM medical necessity review (RAG-grounded, JSON fallback)",
        "Coding validation — LLM coding defensibility review",
    ]
    assert retrieved_policies["coverage_validation"]
    assert retrieved_policies["coding_validation"]


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_manual_and_demo_claims_produce_identical_checks_run_shape(mock_coverage, mock_coding):
    """Same orchestrator call shape for manual vs. demo — checks_run must not
    differ by claim source, only by what actually ran (NPI short-circuit, AI
    enabled/disabled)."""
    mock_coverage.return_value = ([], [])
    mock_coding.return_value = ([], [])

    demo_claim = load_claim({
        "claim_id": "CLM-001", "payer": "Medicare", "npi": "",
        "cpt_codes": ["99213"], "icd10_codes": ["Z00.00"],
        "modifiers": [], "place_of_service": "11", "units": {"99213": 1},
    })
    manual_claim = load_claim(_manual_claim_dict())

    demo_assessment, _ = run_review(demo_claim)
    manual_assessment, _ = run_review(manual_claim)

    assert demo_assessment.checks_run == manual_assessment.checks_run


# ---------------------------------------------------------------------------
# Manual claims never use cached demo AI artifacts
# ---------------------------------------------------------------------------

def test_render_manual_mode_never_calls_cached_demo_helpers():
    """Structural regression guard: app/main.py's manual-entry renderer must
    never reference the cached-demo-artifact helpers, even if a user types a
    claim_id that happens to match a designated demo claim (e.g. "CLM-001")
    — cached artifacts are looked up by exact claim_id and are only ever
    rendered from _render_sample_mode()."""
    import app.main as main_module

    source = inspect.getsource(main_module._render_manual_mode)
    assert "_render_cached_ai_demo" not in source
    assert "_cached_ai_findings_for" not in source


def test_cached_demo_lookup_does_not_match_manual_claim_id():
    """Even if it were called, a manual claim_id would not collide with a
    designated demo claim_id's cached artifacts."""
    from app.main import _cached_ai_findings_for

    assert _cached_ai_findings_for("CLM-MANUAL-TEST-001") is None
    assert _cached_ai_findings_for("CLM-MANUAL-001") is None


# ---------------------------------------------------------------------------
# Manual claims work with no ANTHROPIC_API_KEY (deterministic-only)
# ---------------------------------------------------------------------------

def test_manual_claim_runs_when_api_key_absent(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    claim_dict = _manual_claim_dict()
    claim = load_claim(claim_dict)
    assessment, retrieved_policies = run_review(claim)

    assert assessment.checks_run == CHECKS_RUN
    assert not any(f.rule in ("coverage_validation", "coding_validation") for f in assessment.findings)
    assert retrieved_policies == {"coverage_validation": [], "coding_validation": []}


# ---------------------------------------------------------------------------
# Manual claims work with no ChromaDB/CMS vector store available
# ---------------------------------------------------------------------------

def test_manual_claim_runs_when_vector_store_unavailable(monkeypatch):
    """Simulates the exact ChromaDB-unavailable condition fixed previously
    (VectorStore construction raising RuntimeError) — a manual claim using
    codes present in the curated JSON corpus must still get live AI findings
    via the JSON fallback, not silently fail."""
    def _raise_chromadb_unavailable():
        raise RuntimeError("ChromaDB unavailable; falling back to JSON policy corpus")

    monkeypatch.setattr("agents.coverage_validation._get_vector_store", _raise_chromadb_unavailable)
    monkeypatch.setattr("agents.coding_validation._get_vector_store", _raise_chromadb_unavailable)

    with patch("agents.coverage_validation.anthropic.Anthropic") as mock_cov_anthropic, \
         patch("agents.coding_validation.anthropic.Anthropic") as mock_coding_anthropic:
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        def _no_concern_response(tool_name):
            block = SimpleNamespace(type="tool_use", name=tool_name, input={"reason": "no concern"})
            response = MagicMock()
            response.content = [block]
            return response

        mock_cov_anthropic.return_value.messages.create.return_value = _no_concern_response("no_coverage_concern")
        mock_coding_anthropic.return_value.messages.create.return_value = _no_concern_response("no_coding_concern")

        claim_dict = _manual_claim_dict()  # CPT 99213 + ICD Z00.00 — in the JSON corpus
        claim = load_claim(claim_dict)
        assessment, retrieved_policies = run_review(claim)

    assert "Coverage validation — LLM medical necessity review (RAG-grounded, JSON fallback)" in assessment.checks_run
    assert all(p.get("retrieval_source") == "json_fallback" for p in retrieved_policies["coverage_validation"])
    assert all(p.get("retrieval_source") == "json_fallback" for p in retrieved_policies["coding_validation"])


# ---------------------------------------------------------------------------
# Audit trail supports manual claim IDs
# ---------------------------------------------------------------------------

def test_audit_trail_saves_manual_claim_accept_decision(tmp_path):
    repo = AuditRepository(db_path=tmp_path / "manual_audit.db")
    repo.initialize_database()

    decision = AuditDecision(
        claim_id="CLM-MANUAL-TEST-001",
        finding_id="manual123456",
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
        reviewer_name="Dr. Manual",
        model_version="rule_layer_v0.1",
        prompt_version="n/a",
    )
    repo.save_decision(decision)

    rows = repo.get_decisions(claim_id="CLM-MANUAL-TEST-001")
    assert len(rows) == 1
    assert rows[0]["finding_id"] == "manual123456"
    assert rows[0]["user_decision"] == "accepted"


def test_audit_trail_saves_manual_claim_override_decision(tmp_path):
    repo = AuditRepository(db_path=tmp_path / "manual_audit_override.db")
    repo.initialize_database()

    decision = AuditDecision(
        claim_id="CLM-MANUAL-TEST-002",
        finding_id="manual789012",
        source="agent_layer",
        severity="MEDIUM",
        issue="Coverage concern",
        recommendation="Review documentation.",
        citation_source="LCD",
        citation_doc_id="LCD_TEST",
        citation_section="Indications",
        citation_edition="",
        confidence=0.8,
        user_decision="overridden",
        override_reason="Provider confirmed medical necessity in chart.",
        reviewer_name="Dr. Manual",
        model_version="claude-sonnet-4-6",
        prompt_version="n/a",
    )
    repo.save_decision(decision)

    rows = repo.get_decisions(claim_id="CLM-MANUAL-TEST-002")
    assert len(rows) == 1
    assert rows[0]["user_decision"] == "overridden"
    assert rows[0]["override_reason"] == "Provider confirmed medical necessity in chart."


# ---------------------------------------------------------------------------
# Streamlit smoke path
# ---------------------------------------------------------------------------

def test_manual_mode_renders_without_exception(monkeypatch):
    """Switch to 'Enter manually' and render — no button click (and therefore
    no live API/network call), matching the existing AppTest convention in
    tests/test_app_ai_disabled.py. Catches import/render-time regressions in
    the manual-entry form itself."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("dotenv.load_dotenv", return_value=False):
        at = AppTest.from_file("app/main.py", default_timeout=150)
        at.run()
        at.radio[0].set_value("Enter manually").run()

    assert not at.exception
    assert any("Run Full Review" in btn.label for btn in at.button)
    assert any("Review Claim" in btn.label for btn in at.button)
