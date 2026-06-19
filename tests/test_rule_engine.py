"""
Tests for the deterministic rule engine.

All tests use inline claim dicts — no files, no network, no external dependencies.
"""

import pytest
from rules.rule_engine import load_claim, review_claim, overall_risk, CHECKS_RUN


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_claim(**overrides) -> dict:
    """Base clean claim; override fields as needed.

    NPI is blank by default — NPI validation is tested in test_rules.py.
    Blanking here avoids Luhn failures short-circuiting the coding checks
    these tests are designed to exercise.
    """
    base = {
        "claim_id": "TEST-BASE",
        "payer": "Medicare Part B",
        "npi": "",
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
    """Uses J02.0 (Streptococcal pharyngitis) rather than the default J06.9 —
    J06.9 itself is an unspecified diagnosis, so it now legitimately raises a
    MEDIUM icd10_unspecified finding (see tests/test_icd10.py)."""
    claim = load_claim(_make_claim(
        cpt_codes=["99213", "85025"],
        icd10_codes=["J02.0"],
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


# ---------------------------------------------------------------------------
# Finding structure — finding_id, source, Citation
# ---------------------------------------------------------------------------

def test_every_finding_has_nonempty_finding_id():
    """rule_engine must stamp a non-empty finding_id on every finding."""
    claim = load_claim(_make_claim(
        cpt_codes=["99214", "80053", "80048"],
        icd10_codes=["Z00.00"],
    ))
    findings = review_claim(claim)
    assert findings, "Expected at least one finding for this claim"
    for f in findings:
        assert f.finding_id, f"finding_id is empty for rule='{f.rule}'"


def test_finding_ids_are_unique_within_a_claim():
    """Multiple findings on the same claim must each have a distinct finding_id."""
    claim = load_claim(_make_claim(
        cpt_codes=["99214", "80053", "80048"],
        icd10_codes=["Z00.00"],
    ))
    findings = review_claim(claim)
    ids = [f.finding_id for f in findings]
    assert len(ids) == len(set(ids)), f"Duplicate finding_ids: {ids}"


def test_finding_id_is_stable_across_calls():
    """Same claim + rule + issue must always produce the same finding_id."""
    claim_dict = _make_claim(cpt_codes=["80053", "80048"], icd10_codes=["I10"])
    run1 = review_claim(load_claim(claim_dict))
    run2 = review_claim(load_claim(claim_dict))
    assert run1[0].finding_id == run2[0].finding_id, (
        "finding_id changed between calls for the same input"
    )


def test_every_finding_source_is_rule_layer():
    """All Sprint 1 findings must carry source='rule_layer'."""
    claim = load_claim(_make_claim(
        cpt_codes=["99214", "80053", "80048"],
        icd10_codes=["Z00.00"],
    ))
    findings = review_claim(claim)
    for f in findings:
        assert f.source == "rule_layer", (
            f"Expected source='rule_layer', got '{f.source}' for rule='{f.rule}'"
        )


def test_every_finding_has_structured_citation():
    """Citation must be a Citation object with all required fields populated."""
    from rules.models import Citation
    claim = load_claim(_make_claim(
        cpt_codes=["99214", "80053", "80048"],
        icd10_codes=["Z00.00"],
    ))
    findings = review_claim(claim)
    for f in findings:
        assert isinstance(f.citation, Citation), (
            f"citation is not a Citation object for rule='{f.rule}'"
        )
        assert f.citation.source, f"citation.source is empty for rule='{f.rule}'"
        assert f.citation.doc_id, f"citation.doc_id is empty for rule='{f.rule}'"
        assert f.citation.section, f"citation.section is empty for rule='{f.rule}'"
        assert f.citation.edition, f"citation.edition is empty for rule='{f.rule}'"


def test_ncci_citation_has_excerpt():
    """NCCI findings should include an excerpt identifying the edit pair."""
    claim = load_claim(_make_claim(
        cpt_codes=["80053", "80048"],
        icd10_codes=["I10"],
    ))
    findings = review_claim(claim)
    ncci_finding = next(f for f in findings if f.rule == "ncci_ptp")
    assert ncci_finding.citation.excerpt, "NCCI finding should have a citation excerpt"
    assert "80053" in ncci_finding.citation.excerpt
    assert "80048" in ncci_finding.citation.excerpt


def test_dx_conflict_citation_source_is_icd10():
    """Dx-procedure conflict findings must cite ICD-10-CM."""
    claim = load_claim(_make_claim(
        cpt_codes=["99214"],
        icd10_codes=["Z00.00"],
    ))
    findings = review_claim(claim)
    dx_finding = next(f for f in findings if f.rule == "dx_procedure_conflict")
    assert dx_finding.citation.source == "ICD-10-CM"


def test_modifier_finding_citation_source_is_ncci_policy():
    """Missing-modifier findings must cite the NCCI Policy Manual."""
    claim = load_claim(_make_claim(
        cpt_codes=["99214"],
        icd10_codes=["Z00.00"],
        modifiers=[],
    ))
    findings = review_claim(claim)
    mod_finding = next(f for f in findings if f.rule == "missing_modifier_25")
    assert mod_finding.citation.source == "NCCI Policy Manual"


# ---------------------------------------------------------------------------
# CHECKS_RUN metadata
# ---------------------------------------------------------------------------

def test_checks_run_is_nonempty_list_of_strings():
    """CHECKS_RUN must be a non-empty list of strings for UI consumption."""
    assert isinstance(CHECKS_RUN, list)
    assert len(CHECKS_RUN) >= 5, "Expected at least 5 checks (NPI, NCCI, MUE, dx, modifier)"
    for label in CHECKS_RUN:
        assert isinstance(label, str) and label, "Each CHECKS_RUN entry must be a non-empty string"


def test_checks_run_covers_all_active_rule_modules():
    """CHECKS_RUN must mention NPI, NCCI, MUE, and code-validity checks."""
    combined = " ".join(CHECKS_RUN).upper()
    assert "NPI" in combined, "CHECKS_RUN missing NPI check"
    assert "NCCI" in combined, "CHECKS_RUN missing NCCI PTP check"
    assert "MUE" in combined, "CHECKS_RUN missing MUE check"
    assert "MODIFIER" in combined or "VALIDITY" in combined, (
        "CHECKS_RUN missing code-validity / modifier check"
    )


def test_npi_high_finding_short_circuits_engine():
    """Invalid NPI must return only NPI findings — NCCI/MUE checks must not run."""
    claim = load_claim(_make_claim(
        npi="1234567890",            # fails Luhn
        cpt_codes=["80053", "80048"],  # would trigger NCCI if NPI were valid
        icd10_codes=["I10"],
    ))
    findings = review_claim(claim)
    assert all(f.rule == "npi_invalid" for f in findings), (
        "Expected only npi_invalid findings when NPI Luhn fails"
    )
    assert any(f.severity == "HIGH" for f in findings)
