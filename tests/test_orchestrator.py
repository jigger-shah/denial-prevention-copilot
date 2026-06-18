"""
Tests for agents/orchestrator.py — run_review() end-to-end over rule layer + coverage agent.

No real Anthropic API calls. agents.orchestrator.validate_coverage is patched
directly (the name orchestrator imported into its own namespace), matching the
mocking boundary convention used in tests/test_coverage_validation.py.

Scope (Phase 7, light orchestrator): Documentation Review and Coding Validation
are deferred — see docs/Roadmap.md. Tests explicitly assert no placeholder
finding for either ever appears in a RiskAssessment.
"""

from unittest.mock import patch

from agents.orchestrator import run_review
from rules.models import Citation, ClaimIn, Finding
from rules.rule_engine import CHECKS_RUN


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


# ---------------------------------------------------------------------------
# Deterministic-only claim (no codes that trigger rule findings, no coverage call needed)
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coverage")
def test_clean_claim_returns_clean_score_no_findings(mock_validate_coverage):
    mock_validate_coverage.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert result.score == "CLEAN"
    assert result.findings == []
    assert result.escalation_required is False
    mock_validate_coverage.assert_called_once()


# ---------------------------------------------------------------------------
# Rule + coverage findings combined
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coverage")
def test_rule_and_coverage_findings_combined_into_one_risk_assessment(mock_validate_coverage):
    mock_validate_coverage.return_value = [_coverage_finding()]

    # 80053 + 80048 trigger an NCCI bundling finding; Z00.00 + 99214 trigger dx conflict + modifier 25
    result = run_review(_claim(cpt_codes=["99214", "80053", "80048"], icd10_codes=["Z00.00"]))

    sources = {f.source for f in result.findings}
    assert "rule_layer" in sources
    assert "agent_layer" in sources
    assert any(f.rule == "coverage_validation" for f in result.findings)
    assert result.score in {"HIGH", "MEDIUM"}
    mock_validate_coverage.assert_called_once()


# ---------------------------------------------------------------------------
# NPI HIGH short-circuit skips the coverage agent entirely
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coverage")
def test_npi_high_short_circuit_skips_coverage_agent(mock_validate_coverage):
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


# ---------------------------------------------------------------------------
# checks_run content
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coverage")
def test_checks_run_includes_all_rule_checks_and_coverage_when_not_short_circuited(mock_validate_coverage):
    mock_validate_coverage.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    for label in CHECKS_RUN:
        assert label in result.checks_run
    assert any("coverage" in label.lower() for label in result.checks_run)


@patch("agents.orchestrator.validate_coverage")
def test_checks_run_is_npi_only_when_short_circuited(mock_validate_coverage):
    claim = _claim(npi="1234567890", cpt_codes=["80053"], icd10_codes=["Z00.00"])

    result = run_review(claim)

    assert result.checks_run == [CHECKS_RUN[0]]
    assert not any("coverage" in label.lower() for label in result.checks_run)


# ---------------------------------------------------------------------------
# escalation_required logic
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coverage")
def test_escalation_required_when_coverage_finding_has_low_confidence(mock_validate_coverage):
    mock_validate_coverage.return_value = [_coverage_finding(confidence=0.5)]

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert result.escalation_required is True


@patch("agents.orchestrator.validate_coverage")
def test_escalation_not_required_when_all_findings_high_confidence(mock_validate_coverage):
    mock_validate_coverage.return_value = [_coverage_finding(confidence=0.9)]

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert result.escalation_required is False


# ---------------------------------------------------------------------------
# No placeholder findings for deferred agents (Documentation Review, Coding Validation)
# ---------------------------------------------------------------------------

@patch("agents.orchestrator.validate_coverage")
def test_no_documentation_review_placeholder_finding_ever_appears(mock_validate_coverage):
    mock_validate_coverage.return_value = [_coverage_finding()]

    result = run_review(_claim(cpt_codes=["99214", "80053", "80048"], icd10_codes=["Z00.00"]))

    assert not any(f.rule == "documentation_review" for f in result.findings)
    assert not any("documentation review" in f.issue.lower() for f in result.findings)
    assert not any("not yet implemented" in f.issue.lower() for f in result.findings)
    assert not any("not implemented" in f.recommendation.lower() for f in result.findings)


@patch("agents.orchestrator.validate_coverage")
def test_no_coding_validation_placeholder_finding_ever_appears(mock_validate_coverage):
    mock_validate_coverage.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert not any(f.rule == "coding_validation" for f in result.findings)


@patch("agents.orchestrator.validate_coverage")
def test_no_documentation_review_label_in_checks_run(mock_validate_coverage):
    mock_validate_coverage.return_value = []

    result = run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))

    assert not any("documentation" in label.lower() for label in result.checks_run)


# ---------------------------------------------------------------------------
# No real network/API calls
# ---------------------------------------------------------------------------

def test_no_anthropic_client_constructed_when_coverage_mocked():
    """Sanity check: validate_coverage is fully replaced by the mock in every test above."""
    with patch("agents.orchestrator.validate_coverage") as mock_validate_coverage, \
         patch("anthropic.Anthropic") as mock_anthropic:
        mock_validate_coverage.return_value = []
        run_review(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))
        mock_anthropic.assert_not_called()
