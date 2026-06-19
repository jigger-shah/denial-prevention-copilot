"""
Tests for agents/denial_prevention.py — pure synthesis logic, no I/O, no LLM.

No mocking needed: synthesize() is a deterministic function over plain
dataclasses. These tests construct Finding objects directly.
"""

from agents.denial_prevention import CONFIDENCE_REVIEW_THRESHOLD, synthesize
from rules.models import Citation, Finding


def _finding(severity="MEDIUM", confidence=0.9, rule="test_rule", issue="issue"):
    return Finding(
        rule=rule,
        severity=severity,
        issue=issue,
        recommendation="Do something.",
        citation=Citation(source="test", doc_id="DOC", section="Section", edition="v1"),
        confidence=confidence,
    )


def test_no_findings_at_all_is_clean_no_escalation():
    result = synthesize([], [], [], checks_run=["NPI"])

    assert result.score == "CLEAN"
    assert result.findings == []
    assert result.escalation_required is False
    assert result.checks_run == ["NPI"]


def test_single_high_rule_finding_drives_score():
    rule_findings = [_finding(severity="HIGH", confidence=0.95)]
    result = synthesize(rule_findings, [], [], checks_run=["NPI", "NCCI"])

    assert result.score == "HIGH"
    assert len(result.findings) == 1
    assert result.escalation_required is False  # confidence 0.95 >= threshold


def test_rule_and_coverage_findings_combined_in_one_assessment():
    rule_findings = [_finding(severity="MEDIUM", rule="ncci", issue="bundling issue")]
    coverage_findings = [_finding(severity="HIGH", rule="coverage_validation", issue="coverage issue")]

    result = synthesize(rule_findings, coverage_findings, [], checks_run=["NPI", "NCCI", "Coverage"])

    assert len(result.findings) == 2
    assert result.score == "HIGH"  # highest severity across both sources
    assert {f.issue for f in result.findings} == {"bundling issue", "coverage issue"}


def test_findings_sorted_high_before_medium_before_low():
    rule_findings = [_finding(severity="LOW", issue="low one"), _finding(severity="HIGH", issue="high one")]
    coverage_findings = [_finding(severity="MEDIUM", issue="medium one")]

    result = synthesize(rule_findings, coverage_findings, [], checks_run=[])

    assert [f.severity for f in result.findings] == ["HIGH", "MEDIUM", "LOW"]


def test_escalation_required_when_any_finding_below_confidence_threshold():
    low_confidence = _finding(severity="MEDIUM", confidence=CONFIDENCE_REVIEW_THRESHOLD - 0.01)
    result = synthesize([low_confidence], [], [], checks_run=[])

    assert result.escalation_required is True


def test_escalation_not_required_when_all_findings_at_or_above_threshold():
    at_threshold = _finding(severity="MEDIUM", confidence=CONFIDENCE_REVIEW_THRESHOLD)
    result = synthesize([at_threshold], [], [], checks_run=[])

    assert result.escalation_required is False


def test_escalation_triggered_by_coverage_finding_alone():
    rule_findings = [_finding(severity="LOW", confidence=0.95)]
    coverage_findings = [_finding(severity="MEDIUM", confidence=0.5, rule="coverage_validation")]

    result = synthesize(rule_findings, coverage_findings, [], checks_run=[])

    assert result.escalation_required is True


def test_checks_run_is_passed_through_unchanged():
    checks = ["NPI", "NCCI", "MUE", "Code validity (dx)", "Code validity (modifier)", "Coverage validation"]
    result = synthesize([], [], [], checks_run=checks)

    assert result.checks_run == checks
    assert result.checks_run is checks  # pass-through, not a copy or mutation


# ---------------------------------------------------------------------------
# v1.3: coding findings
# ---------------------------------------------------------------------------

def test_coding_findings_included_in_risk_assessment():
    coding_findings = [_finding(severity="MEDIUM", rule="coding_validation", issue="coding issue")]

    result = synthesize([], [], coding_findings, checks_run=["NPI", "Coding validation"])

    assert len(result.findings) == 1
    assert result.findings[0].rule == "coding_validation"


def test_coding_finding_drives_score_when_highest_severity():
    rule_findings = [_finding(severity="LOW", rule="ncci")]
    coverage_findings = [_finding(severity="MEDIUM", rule="coverage_validation")]
    coding_findings = [_finding(severity="HIGH", rule="coding_validation", issue="coding issue")]

    result = synthesize(rule_findings, coverage_findings, coding_findings, checks_run=[])

    assert result.score == "HIGH"
    assert [f.severity for f in result.findings] == ["HIGH", "MEDIUM", "LOW"]


def test_escalation_triggered_by_coding_finding_alone():
    rule_findings = [_finding(severity="LOW", confidence=0.95)]
    coding_findings = [_finding(severity="MEDIUM", confidence=0.5, rule="coding_validation")]

    result = synthesize(rule_findings, [], coding_findings, checks_run=[])

    assert result.escalation_required is True


def test_rule_coverage_and_coding_findings_all_combined():
    rule_findings = [_finding(severity="LOW", rule="ncci", issue="bundling issue")]
    coverage_findings = [_finding(severity="MEDIUM", rule="coverage_validation", issue="coverage issue")]
    coding_findings = [_finding(severity="HIGH", rule="coding_validation", issue="coding issue")]

    result = synthesize(rule_findings, coverage_findings, coding_findings, checks_run=[])

    assert len(result.findings) == 3
    assert {f.issue for f in result.findings} == {"bundling issue", "coverage issue", "coding issue"}
