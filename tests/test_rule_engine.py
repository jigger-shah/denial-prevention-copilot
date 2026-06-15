"""
Tests for the deterministic rule engine.

All tests use inline claim dicts — no files, no network, no external dependencies.
"""

import pytest
from rules.rule_engine import load_claim, review_claim, overall_risk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_claim(**overrides) -> dict:
    """Base clean claim; override fields as needed."""
    base = {
        "claim_id": "TEST-BASE",
        "payer": "Medicare Part B",
        "npi": "1234567890",
        "cpt_codes": ["99213"],
        "icd10_codes": ["J06.9"],
        "modifiers": [],
        "place_of_service": "11",
        "units": {"99213": 1},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# NCCI bundling
# ---------------------------------------------------------------------------

def test_bundled_code_pair_raises_high_finding():
    """80048 billed with 80053 must produce a HIGH NCCI finding."""
    claim = load_claim(_make_claim(
        cpt_codes=["99213", "80053", "80048"],
        icd10_codes=["I10"],
    ))
    findings = review_claim(claim)
    ncci_findings = [f for f in findings if f.rule == "ncci_ptp"]
    assert ncci_findings, "Expected at least one NCCI PTP finding"
    assert ncci_findings[0].severity == "HIGH"


def test_bundled_code_finding_names_both_codes():
    """The finding issue text should reference both the component and comprehensive code."""
    claim = load_claim(_make_claim(
        cpt_codes=["80053", "80048"],
        icd10_codes=["I10"],
    ))
    findings = review_claim(claim)
    ncci = [f for f in findings if f.rule == "ncci_ptp"][0]
    assert "80048" in ncci.issue
    assert "80053" in ncci.issue


def test_no_bundling_finding_when_only_one_code_present():
    """80053 alone should not trigger a bundling finding."""
    claim = load_claim(_make_claim(
        cpt_codes=["99213", "80053"],
        icd10_codes=["I10"],
    ))
    findings = review_claim(claim)
    assert not any(f.rule == "ncci_ptp" for f in findings)


# ---------------------------------------------------------------------------
# Diagnosis-to-procedure conflict
# ---------------------------------------------------------------------------

def test_diagnosis_mismatch_raises_high_finding():
    """Z00.00 billed with a problem-oriented E/M must produce a HIGH finding."""
    claim = load_claim(_make_claim(
        cpt_codes=["99214"],
        icd10_codes=["Z00.00"],
    ))
    findings = review_claim(claim)
    dx_findings = [f for f in findings if f.rule == "dx_procedure_conflict"]
    assert dx_findings, "Expected a dx-procedure conflict finding"
    assert dx_findings[0].severity == "HIGH"


def test_diagnosis_mismatch_not_raised_for_preventive_code():
    """Z00.00 with a preventive E/M code (99395) should not trigger a conflict."""
    claim = load_claim(_make_claim(
        cpt_codes=["99395"],
        icd10_codes=["Z00.00"],
    ))
    findings = review_claim(claim)
    assert not any(f.rule == "dx_procedure_conflict" for f in findings)


# ---------------------------------------------------------------------------
# Missing modifier 25
# ---------------------------------------------------------------------------

def test_missing_modifier_25_raises_medium_finding():
    """Problem E/M + preventive dx + no modifier 25 must produce a MEDIUM finding."""
    claim = load_claim(_make_claim(
        cpt_codes=["99214"],
        icd10_codes=["Z00.00"],
        modifiers=[],
    ))
    findings = review_claim(claim)
    mod_findings = [f for f in findings if f.rule == "missing_modifier_25"]
    assert mod_findings, "Expected a missing modifier 25 finding"
    assert mod_findings[0].severity == "MEDIUM"


def test_modifier_25_present_suppresses_finding():
    """When modifier 25 is present the missing-modifier finding should not appear."""
    claim = load_claim(_make_claim(
        cpt_codes=["99214"],
        icd10_codes=["Z00.00"],
        modifiers=["25"],
    ))
    findings = review_claim(claim)
    assert not any(f.rule == "missing_modifier_25" for f in findings)


# ---------------------------------------------------------------------------
# Clean claim
# ---------------------------------------------------------------------------

def test_clean_claim_returns_no_high_severity_findings():
    """A well-coded URI claim should return no HIGH-severity findings."""
    claim = load_claim(_make_claim(
        cpt_codes=["99213", "85025"],
        icd10_codes=["J06.9"],
    ))
    findings = review_claim(claim)
    assert not any(f.severity == "HIGH" for f in findings)


def test_clean_claim_overall_risk_is_clean():
    claim = load_claim(_make_claim(
        cpt_codes=["99213", "85025"],
        icd10_codes=["J06.9"],
    ))
    findings = review_claim(claim)
    assert overall_risk(findings) == "CLEAN"


# ---------------------------------------------------------------------------
# Findings ordering
# ---------------------------------------------------------------------------

def test_findings_sorted_high_before_medium():
    """review_claim must return HIGH findings before MEDIUM findings."""
    claim = load_claim(_make_claim(
        cpt_codes=["99214", "80053", "80048"],
        icd10_codes=["Z00.00"],
    ))
    findings = review_claim(claim)
    severities = [f.severity for f in findings]
    high_indices = [i for i, s in enumerate(severities) if s == "HIGH"]
    medium_indices = [i for i, s in enumerate(severities) if s == "MEDIUM"]
    if high_indices and medium_indices:
        assert max(high_indices) < min(medium_indices)


# ---------------------------------------------------------------------------
# overall_risk helper
# ---------------------------------------------------------------------------

def test_overall_risk_high_when_any_high():
    claim = load_claim(_make_claim(cpt_codes=["80053", "80048"], icd10_codes=["I10"]))
    findings = review_claim(claim)
    assert overall_risk(findings) == "HIGH"


def test_overall_risk_clean_when_no_findings():
    assert overall_risk([]) == "CLEAN"
