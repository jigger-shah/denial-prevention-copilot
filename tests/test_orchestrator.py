"""
Tests for agents/orchestrator.py — run_review() end-to-end over rule layer +
coverage agent + coding agent.

No real Anthropic API calls. agents.orchestrator.validate_coverage and
agents.orchestrator.validate_coding are patched directly (the names
orchestrator imported into its own namespace), matching the mocking
boundary convention used in tests/test_coverage_validation.py and
tests/test_coding_validation.py.

Scope (v1.3): Documentation Review remains deferred — see docs/Roadmap.md.
Tests explicitly assert no placeholder finding for it ever appears in a
RiskAssessment. Coding Validation is now a real, implemented agent (no
longer a deferred placeholder) — see test_coding_validation.py for its
unit tests and the "Coding agent integration" section below for its
orchestrator-level behavior.
"""

from unittest.mock import patch

import pytest

from agents.orchestrator import run_review
from rules.models import Citation, ClaimIn, Finding
from rules.rule_engine import CHECKS_RUN


@pytest.fixture(autouse=True)
def _api_key_present(monkeypatch):
    """
    Every test in this file mocks validate_coverage/validate_coding directly and
    expects run_review() to call them — so ANTHROPIC_API_KEY must read as present
    regardless of whether a real .env exists on the machine running the suite
    (e.g. a fresh public clone with no key). The "no key" disabled path has its
    own explicit tests below (see "AI disabled when no API key").
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def _claim(npi="", cpt_codes=None, icd10_codes=None, claim_id="CLM-ORCH-001"):
    return ClaimIn(
        claim_id=claim_id,
        payer="MEDICARE",
        npi=npi,
        cpt_codes=cpt_codes or [],
        icd10_codes=icd10_codes or [],
        modifiers=[],
        place_of_service="11",
        units={},
    )


def _coverage_finding(confidence=0.85):
    return Finding(
        rule="coverage_validation",
        severity="MEDIUM",
        issue="Coverage concern",
        recommendation="Review documentation.",
        citation=Citation(source="coverage_validation", doc_id="LCD_TEST", section="Indications", edition=""),
        confidence=confidence,
        source="agent_layer",
    )


def _coding_finding(confidence=0.85):
    return Finding(
        rule="coding_validation",
        severity="MEDIUM",
        issue="Coding defensibility concern",
        recommendation="Add a more specific diagnosis code.",
        citation=Citation(source="coding_validation", doc_id="LCD_TEST", section="Indications", edition=""),
        confidence=confidence,
        source="agent_layer",
    )


# ---------------------------------------------------------------------------
# Deterministic-only claim (no codes that trigger rule findings, no agent calls needed)
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_clean_claim_returns_clean_score_no_findings(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = []
    mock_validate_coding.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert result.score == "CLEAN"
    assert result.findings == []
    assert result.escalation_required is False
    mock_validate_coverage.assert_called_once()
    mock_validate_coding.assert_called_once()


# ---------------------------------------------------------------------------
# Rule + coverage findings combined
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_rule_and_coverage_findings_combined_into_one_risk_assessment(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = [_coverage_finding()]
    mock_validate_coding.return_value = []

    # 80053 + 80048 trigger an NCCI bundling finding; Z00.00 + 99214 trigger dx conflict + modifier 25
    result = run_review(_claim(cpt_codes=["99214", "80053", "80048"], icd10_codes=["Z00.00"]))

    sources = {f.source for f in result.findings}
    assert "rule_layer" in sources
    assert "agent_layer" in sources
    assert any(f.rule == "coverage_validation" for f in result.findings)
    assert result.score in {"HIGH", "MEDIUM"}
    mock_validate_coverage.assert_called_once()


# ---------------------------------------------------------------------------
# NPI HIGH short-circuit skips both agents entirely
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_npi_high_short_circuit_skips_coverage_agent(mock_validate_coverage, mock_validate_coding):
    claim = _claim(
        npi="1234567890",              # fails Luhn -> HIGH npi_invalid, short-circuits rule_engine
        cpt_codes=["80053", "80048"],  # would otherwise trigger NCCI
        icd10_codes=["Z00.00"],
    )

    result = run_review(claim)

    mock_validate_coverage.assert_not_called()
    assert all(f.rule == "npi_invalid" for f in result.findings)
    assert result.score == "HIGH"
    assert result.checks_run == [CHECKS_RUN[0]]


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_npi_high_short_circuit_skips_coding_agent(mock_validate_coverage, mock_validate_coding):
    claim = _claim(
        npi="1234567890",
        cpt_codes=["80053", "80048"],
        icd10_codes=["Z00.00"],
    )

    run_review(claim)

    mock_validate_coding.assert_not_called()


# ---------------------------------------------------------------------------
# checks_run content
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_checks_run_includes_all_rule_checks_and_coverage_when_not_short_circuited(
    mock_validate_coverage, mock_validate_coding
):
    mock_validate_coverage.return_value = []
    mock_validate_coding.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    for label in CHECKS_RUN:
        assert label in result.checks_run
    assert any("coverage" in label.lower() for label in result.checks_run)


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_checks_run_includes_coding_label_when_not_short_circuited(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = []
    mock_validate_coding.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert any("coding" in label.lower() for label in result.checks_run)


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_checks_run_is_npi_only_when_short_circuited(mock_validate_coverage, mock_validate_coding):
    claim = _claim(npi="1234567890", cpt_codes=["80053"], icd10_codes=["Z00.00"])

    result = run_review(claim)

    assert result.checks_run == [CHECKS_RUN[0]]
    assert not any("coverage" in label.lower() for label in result.checks_run)
    assert not any("coding" in label.lower() for label in result.checks_run)


# ---------------------------------------------------------------------------
# escalation_required logic
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_escalation_required_when_coverage_finding_has_low_confidence(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = [_coverage_finding(confidence=0.5)]
    mock_validate_coding.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert result.escalation_required is True


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_escalation_not_required_when_all_findings_high_confidence(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = [_coverage_finding(confidence=0.9)]
    mock_validate_coding.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert result.escalation_required is False


# ---------------------------------------------------------------------------
# No placeholder findings for deferred agents (Documentation Review)
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_no_documentation_review_placeholder_finding_ever_appears(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = [_coverage_finding()]
    mock_validate_coding.return_value = []

    result = run_review(_claim(cpt_codes=["99214", "80053", "80048"], icd10_codes=["Z00.00"]))

    assert not any(f.rule == "documentation_review" for f in result.findings)
    assert not any("documentation review" in f.issue.lower() for f in result.findings)
    assert not any("not yet implemented" in f.issue.lower() for f in result.findings)
    assert not any("not implemented" in f.recommendation.lower() for f in result.findings)


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_no_documentation_review_label_in_checks_run(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = []
    mock_validate_coding.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert not any("documentation" in label.lower() for label in result.checks_run)


# ---------------------------------------------------------------------------
# Coding agent integration (v1.3)
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_coding_findings_appear_in_risk_assessment(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = []
    mock_validate_coding.return_value = [_coding_finding()]

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert any(f.rule == "coding_validation" for f in result.findings)
    mock_validate_coding.assert_called_once()


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_coding_findings_combined_with_coverage_and_rule_findings(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = [_coverage_finding()]
    mock_validate_coding.return_value = [_coding_finding()]

    result = run_review(_claim(cpt_codes=["99214", "80053", "80048"], icd10_codes=["Z00.00"]))

    rules_seen = {f.rule for f in result.findings}
    assert "coverage_validation" in rules_seen
    assert "coding_validation" in rules_seen
    assert any(f.rule not in {"coverage_validation", "coding_validation"} for f in result.findings)  # rule layer


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_coding_finding_drives_overall_risk_score(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = []
    mock_validate_coding.return_value = [_coding_finding(confidence=0.9)]
    # bump severity to HIGH for this test via a fresh finding
    high_coding_finding = Finding(
        rule="coding_validation",
        severity="HIGH",
        issue="Diagnosis lacks specificity for billed procedure",
        recommendation="Use a more specific ICD-10 code.",
        citation=Citation(source="coding_validation", doc_id="LCD_TEST", section="Indications", edition=""),
        confidence=0.9,
        source="agent_layer",
    )
    mock_validate_coding.return_value = [high_coding_finding]

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert result.score == "HIGH"


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_escalation_required_when_coding_finding_has_low_confidence(mock_validate_coverage, mock_validate_coding):
    mock_validate_coverage.return_value = []
    mock_validate_coding.return_value = [_coding_finding(confidence=0.5)]

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert result.escalation_required is True


@patch("agents.orchestrator.validate_coding")
@patch("agents.orchestrator.validate_coverage")
def test_coverage_agent_called_before_coding_agent_sequentially(mock_validate_coverage, mock_validate_coding):
    """No parallel execution: both agents are called, coverage first (per orchestrator source order)."""
    call_order = []
    mock_validate_coverage.side_effect = lambda claim: call_order.append("coverage") or []
    mock_validate_coding.side_effect = lambda claim: call_order.append("coding") or []

    run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert call_order == ["coverage", "coding"]


# ---------------------------------------------------------------------------
# No real network/API calls
# ---------------------------------------------------------------------------

def test_no_anthropic_client_constructed_when_agents_mocked():
    """Sanity check: both agents are fully replaced by mocks in every test above."""
    with patch("agents.orchestrator.validate_coverage") as mock_validate_coverage, \
         patch("agents.orchestrator.validate_coding") as mock_validate_coding, \
         patch("anthropic.Anthropic") as mock_anthropic:
        mock_validate_coverage.return_value = []
        mock_validate_coding.return_value = []
        run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))
        mock_anthropic.assert_not_called()


# ---------------------------------------------------------------------------
# AI disabled when no API key (v1.6 — public release hardening, TD-12)
# ---------------------------------------------------------------------------

def test_agents_not_called_when_api_key_missing(monkeypatch):
    """run_review() must not even attempt to call the agents when no key is set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("agents.orchestrator.validate_coverage") as mock_validate_coverage, \
         patch("agents.orchestrator.validate_coding") as mock_validate_coding:
        result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

        mock_validate_coverage.assert_not_called()
        mock_validate_coding.assert_not_called()
        assert result.score == "CLEAN"


def test_no_anthropic_client_constructed_when_api_key_missing(monkeypatch):
    """No key -> orchestrator never reaches the agents -> no client is ever constructed."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("anthropic.Anthropic") as mock_anthropic:
        run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))
        mock_anthropic.assert_not_called()


def test_checks_run_excludes_ai_labels_when_api_key_missing(monkeypatch):
    """Deterministic checks_run is still reported; coverage/coding labels are not, since they didn't run."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    for label in CHECKS_RUN:
        assert label in result.checks_run
    assert not any("coverage" in label.lower() for label in result.checks_run)
    assert not any("coding" in label.lower() for label in result.checks_run)


def test_deterministic_findings_still_returned_when_api_key_missing(monkeypatch):
    """Rule-layer findings (e.g. NCCI bundling) are unaffected by AI being disabled."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    claim = _claim(cpt_codes=["99214", "80053", "80048"], icd10_codes=["Z00.00"])

    result = run_review(claim)

    assert any(f.source == "rule_layer" for f in result.findings)
    assert not any(f.source == "agent_layer" for f in result.findings)
