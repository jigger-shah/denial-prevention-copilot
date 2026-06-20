"""
Tests for rules/hcpcs.py — curated HCPCS Level II common-code recognition (TD-06).

Deliberately small scope: format detection (letter + 4 digits) plus lookup
against a small curated dict, no file I/O, no loader.
"""

from __future__ import annotations

from rules.hcpcs import check_hcpcs_validity, _KNOWN_HCPCS
from rules.models import ClaimIn
from rules.rule_engine import load_claim, review_claim, CHECKS_RUN


def _make_claim(**overrides) -> ClaimIn:
    base = dict(
        claim_id="TEST-HCPCS-001",
        payer="Medicare",
        npi="",
        cpt_codes=["99213"],
        icd10_codes=["I10"],
        modifiers=[],
        place_of_service="11",
        units={},
    )
    base.update(overrides)
    return ClaimIn(**base)


class TestCheckHcpcsValidity:
    def test_cpt_only_claim_produces_no_finding(self):
        claim = _make_claim(cpt_codes=["99213", "80053"])
        assert check_hcpcs_validity(claim) == []

    def test_recognized_hcpcs_code_produces_no_finding(self):
        claim = _make_claim(cpt_codes=["G0438"])
        assert check_hcpcs_validity(claim) == []

    def test_unrecognized_hcpcs_formatted_code_produces_medium_finding(self):
        claim = _make_claim(cpt_codes=["T9999"])
        findings = check_hcpcs_validity(claim)
        assert len(findings) == 1
        assert findings[0].rule == "hcpcs_unrecognized"
        assert findings[0].severity == "MEDIUM"
        assert "T9999" in findings[0].issue

    def test_lowercase_recognized_code_is_normalized(self):
        claim = _make_claim(cpt_codes=["g0438"])
        assert check_hcpcs_validity(claim) == []

    def test_duplicate_unrecognized_codes_checked_once(self):
        claim = _make_claim(cpt_codes=["T9999", "T9999"])
        findings = check_hcpcs_validity(claim)
        assert len(findings) == 1

    def test_mixed_cpt_and_unrecognized_hcpcs(self):
        claim = _make_claim(cpt_codes=["99213", "T9999"])
        findings = check_hcpcs_validity(claim)
        assert len(findings) == 1
        assert findings[0].rule == "hcpcs_unrecognized"

    def test_finding_has_structured_citation(self):
        claim = _make_claim(cpt_codes=["T9999"])
        finding = check_hcpcs_validity(claim)[0]
        assert finding.citation.source == "HCPCS Level II"
        assert finding.citation.doc_id
        assert finding.citation.excerpt

    def test_source_is_rule_layer(self):
        claim = _make_claim(cpt_codes=["T9999"])
        finding = check_hcpcs_validity(claim)[0]
        assert finding.source == "rule_layer"

    def test_known_hcpcs_set_is_nonempty(self):
        assert len(_KNOWN_HCPCS) > 0


class TestRuleEngineIntegration:
    def test_hcpcs_check_listed_in_checks_run(self):
        assert any("HCPCS" in c for c in CHECKS_RUN)

    def test_unrecognized_hcpcs_surfaces_through_review_claim(self):
        claim = load_claim({
            "claim_id": "TEST-HCPCS-002",
            "payer": "Medicare Part B",
            "npi": "",
            "cpt_codes": ["T9999"],
            "icd10_codes": ["I10"],
            "modifiers": [],
            "place_of_service": "11",
            "units": {},
        })
        findings = review_claim(claim)
        assert any(f.rule == "hcpcs_unrecognized" for f in findings)

    def test_high_npi_finding_short_circuits_hcpcs_check(self):
        claim = load_claim({
            "claim_id": "TEST-HCPCS-003",
            "payer": "Medicare Part B",
            "npi": "1234567890",  # fails Luhn
            "cpt_codes": ["T9999"],
            "icd10_codes": ["I10"],
            "modifiers": [],
            "place_of_service": "11",
            "units": {},
        })
        findings = review_claim(claim)
        assert not any(f.rule == "hcpcs_unrecognized" for f in findings)
        assert any(f.rule == "npi_invalid" for f in findings)

    def test_recognized_hcpcs_produces_no_finding_through_review_claim(self):
        claim = load_claim({
            "claim_id": "TEST-HCPCS-004",
            "payer": "Medicare Part B",
            "npi": "",
            "cpt_codes": ["G0438"],
            "icd10_codes": ["I10"],
            "modifiers": [],
            "place_of_service": "11",
            "units": {},
        })
        findings = review_claim(claim)
        assert not any(f.rule == "hcpcs_unrecognized" for f in findings)
