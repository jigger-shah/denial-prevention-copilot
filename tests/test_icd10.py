"""
Tests for rules/icd10_loader.py and rules/icd10.py.

Test strategy:
  - Loader tests use a small fixed-width fixture file built programmatically
    (avoids parsing the full ~14MB real CMS order file in most tests). The
    real file is only touched by integration tests that explicitly opt in.
  - Rule behavior tests monkeypatch icd10_loader.lookup_icd10 to return
    controlled fixture data — no file I/O needed.
  - Each test clears the lru_cache via icd10_loader._clear_icd10_cache() to
    prevent cross-test contamination.
"""

from __future__ import annotations

import pytest

from rules import icd10_loader
from rules.icd10 import check_icd10_validity
from rules.models import ClaimIn
from rules.rule_engine import load_claim, review_claim, CHECKS_RUN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_claim(**overrides) -> ClaimIn:
    base = dict(
        claim_id="TEST-001",
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


_FIXTURE_TABLE = {
    "I10": {"description": "Essential (primary) hypertension", "billable": True, "source_file": "fixture.txt"},
    "J02.0": {"description": "Streptococcal pharyngitis", "billable": True, "source_file": "fixture.txt"},
    "R10.9": {"description": "Unspecified abdominal pain", "billable": True, "source_file": "fixture.txt"},
}


def _fixture_lookup(code, *args, **kwargs):
    return _FIXTURE_TABLE.get(code.strip().upper())


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the ICD-10 lru_cache before every test to prevent cross-test contamination."""
    icd10_loader._clear_icd10_cache()
    yield
    icd10_loader._clear_icd10_cache()


# ---------------------------------------------------------------------------
# Fixed-width fixture builder
# ---------------------------------------------------------------------------

@pytest.fixture
def icd10_fixture_dir(tmp_path):
    """
    Create a minimal CMS-format fixed-width order file:
    order(5) + space + code(7) + space + billable(1) + space + short(60) + long.
    """
    lines = [
        f"{1:05d} {'I10':<7} 1 {'Essential (primary) hypertension':<60} Essential (primary) hypertension",
        f"{2:05d} {'R109':<7} 1 {'Unspecified abdominal pain':<60} Unspecified abdominal pain",
        f"{3:05d} {'Z0000':<7} 1 {'Encntr gen adult exam w/o abn findings':<60} Encounter for general adult medical examination without abnormal findings",
    ]
    fpath = tmp_path / "icd10cm_order_fixture.txt"
    fpath.write_text("\n".join(lines) + "\n")
    return str(tmp_path)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

class TestDiscoverIcd10File:
    def test_finds_real_order_file(self):
        fpath = icd10_loader.discover_icd10_file("data/reference/icd10")
        assert fpath is not None
        assert fpath.endswith(".txt")

    def test_missing_directory_returns_none(self):
        fpath = icd10_loader.discover_icd10_file("data/reference/nonexistent_dir")
        assert fpath is None

    def test_fixture_dir_returns_file(self, icd10_fixture_dir):
        fpath = icd10_loader.discover_icd10_file(icd10_fixture_dir)
        assert fpath is not None
        assert fpath.endswith(".txt")


# ---------------------------------------------------------------------------
# Loader: reads the fixed-width file and builds the lookup dict
# ---------------------------------------------------------------------------

class TestLoadIcd10Table:
    def test_returns_dict_from_fixture(self, icd10_fixture_dir):
        table = icd10_loader.load_icd10_table(icd10_fixture_dir)
        assert isinstance(table, dict)
        assert len(table) == 3

    def test_code_formatted_with_decimal_point(self, icd10_fixture_dir):
        table = icd10_loader.load_icd10_table(icd10_fixture_dir)
        assert "R10.9" in table
        assert "Z00.00" in table

    def test_three_char_code_unchanged(self, icd10_fixture_dir):
        table = icd10_loader.load_icd10_table(icd10_fixture_dir)
        assert "I10" in table

    def test_entry_has_required_keys(self, icd10_fixture_dir):
        table = icd10_loader.load_icd10_table(icd10_fixture_dir)
        entry = table["I10"]
        assert "description" in entry
        assert "billable" in entry
        assert "source_file" in entry

    def test_empty_dir_falls_back_to_synthetic(self, tmp_path):
        table = icd10_loader.load_icd10_table(str(tmp_path))
        assert table == icd10_loader._SYNTHETIC_ICD10

    def test_result_is_cached(self, icd10_fixture_dir):
        t1 = icd10_loader.load_icd10_table(icd10_fixture_dir)
        t2 = icd10_loader.load_icd10_table(icd10_fixture_dir)
        assert t1 is t2


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class TestLookupIcd10:
    def test_found_code_returns_entry(self, icd10_fixture_dir):
        entry = icd10_loader.lookup_icd10("R10.9", icd10_fixture_dir)
        assert entry is not None
        assert "Unspecified" in entry["description"]

    def test_unknown_code_returns_none(self, icd10_fixture_dir):
        entry = icd10_loader.lookup_icd10("ZZ99.99", icd10_fixture_dir)
        assert entry is None

    def test_code_normalized_to_uppercase(self, icd10_fixture_dir):
        entry = icd10_loader.lookup_icd10(" r10.9 ", icd10_fixture_dir)
        assert entry is not None


# ---------------------------------------------------------------------------
# check_icd10_validity: rule behavior
# ---------------------------------------------------------------------------

class TestCheckIcd10Validity:
    def test_valid_specific_code_produces_no_finding(self, monkeypatch):
        monkeypatch.setattr(icd10_loader, "lookup_icd10", _fixture_lookup)
        claim = _make_claim(icd10_codes=["J02.0"])
        findings = check_icd10_validity(claim)
        assert findings == []

    def test_invalid_code_produces_high_finding(self, monkeypatch):
        monkeypatch.setattr(icd10_loader, "lookup_icd10", _fixture_lookup)
        claim = _make_claim(icd10_codes=["ZZ99.99"])
        findings = check_icd10_validity(claim)
        assert len(findings) == 1
        assert findings[0].rule == "icd10_invalid"
        assert findings[0].severity == "HIGH"
        assert "ZZ99.99" in findings[0].issue

    def test_unspecified_diagnosis_produces_medium_finding(self, monkeypatch):
        monkeypatch.setattr(icd10_loader, "lookup_icd10", _fixture_lookup)
        claim = _make_claim(icd10_codes=["R10.9"])
        findings = check_icd10_validity(claim)
        assert len(findings) == 1
        assert findings[0].rule == "icd10_unspecified"
        assert findings[0].severity == "MEDIUM"
        assert "R10.9" in findings[0].issue

    def test_unknown_code_is_invalid_not_unspecified(self, monkeypatch):
        monkeypatch.setattr(icd10_loader, "lookup_icd10", _fixture_lookup)
        claim = _make_claim(icd10_codes=["Q99.99"])
        findings = check_icd10_validity(claim)
        assert findings[0].rule == "icd10_invalid"

    def test_duplicate_codes_checked_once(self, monkeypatch):
        monkeypatch.setattr(icd10_loader, "lookup_icd10", _fixture_lookup)
        claim = _make_claim(icd10_codes=["R10.9", "R10.9"])
        findings = check_icd10_validity(claim)
        assert len(findings) == 1

    def test_multiple_codes_each_checked(self, monkeypatch):
        monkeypatch.setattr(icd10_loader, "lookup_icd10", _fixture_lookup)
        claim = _make_claim(icd10_codes=["R10.9", "ZZ99.99"])
        findings = check_icd10_validity(claim)
        rules = {f.rule for f in findings}
        assert rules == {"icd10_unspecified", "icd10_invalid"}

    def test_finding_has_structured_citation(self, monkeypatch):
        monkeypatch.setattr(icd10_loader, "lookup_icd10", _fixture_lookup)
        claim = _make_claim(icd10_codes=["R10.9"])
        finding = check_icd10_validity(claim)[0]
        assert finding.citation.doc_id == icd10_loader.ICD10_DOC_ID
        assert finding.citation.edition == icd10_loader.ICD10_VERSION
        assert finding.citation.effective_date == icd10_loader.ICD10_EFFECTIVE_DATE

    def test_source_is_rule_layer(self, monkeypatch):
        monkeypatch.setattr(icd10_loader, "lookup_icd10", _fixture_lookup)
        claim = _make_claim(icd10_codes=["R10.9"])
        finding = check_icd10_validity(claim)[0]
        assert finding.source == "rule_layer"


# ---------------------------------------------------------------------------
# Integration: real CMS file
# ---------------------------------------------------------------------------

class TestCheckIcd10ValidityRealFile:
    def test_z00_00_found_in_real_file(self):
        entry = icd10_loader.lookup_icd10("Z00.00")
        assert entry is not None
        assert "abnormal findings" in entry["description"].lower()

    def test_r10_9_is_unspecified_in_real_file(self):
        claim = _make_claim(icd10_codes=["R10.9"])
        findings = check_icd10_validity(claim)
        assert len(findings) == 1
        assert findings[0].rule == "icd10_unspecified"

    def test_made_up_code_is_invalid_in_real_file(self):
        claim = _make_claim(icd10_codes=["ZZ99.999"])
        findings = check_icd10_validity(claim)
        assert len(findings) == 1
        assert findings[0].rule == "icd10_invalid"

    def test_specific_code_produces_no_finding_in_real_file(self):
        claim = _make_claim(icd10_codes=["J02.0"])
        findings = check_icd10_validity(claim)
        assert findings == []


# ---------------------------------------------------------------------------
# Rule-engine integration
# ---------------------------------------------------------------------------

class TestRuleEngineIntegration:
    def test_icd10_check_listed_in_checks_run(self):
        assert any("ICD-10" in c for c in CHECKS_RUN)

    def test_unspecified_dx_surfaces_through_review_claim(self):
        claim = load_claim({
            "claim_id": "TEST-ICD10-001",
            "payer": "Medicare Part B",
            "npi": "",
            "cpt_codes": ["99214"],
            "icd10_codes": ["R10.9"],
            "modifiers": [],
            "place_of_service": "11",
            "units": {},
        })
        findings = review_claim(claim)
        assert any(f.rule == "icd10_unspecified" for f in findings)

    def test_invalid_dx_surfaces_through_review_claim(self):
        claim = load_claim({
            "claim_id": "TEST-ICD10-002",
            "payer": "Medicare Part B",
            "npi": "",
            "cpt_codes": ["99213"],
            "icd10_codes": ["ZZ99.999"],
            "modifiers": [],
            "place_of_service": "11",
            "units": {},
        })
        findings = review_claim(claim)
        assert any(f.rule == "icd10_invalid" for f in findings)

    def test_high_npi_finding_still_short_circuits_icd10_check(self):
        """A HIGH NPI finding must suppress icd10 findings, same as NCCI/MUE/code_validity."""
        claim = load_claim({
            "claim_id": "TEST-ICD10-003",
            "payer": "Medicare Part B",
            "npi": "1234567890",  # fails Luhn
            "cpt_codes": ["99213"],
            "icd10_codes": ["ZZ99.999"],
            "modifiers": [],
            "place_of_service": "11",
            "units": {},
        })
        findings = review_claim(claim)
        assert not any(f.rule in ("icd10_invalid", "icd10_unspecified") for f in findings)
        assert any(f.rule == "npi_invalid" for f in findings)

    def test_specific_dx_produces_no_icd10_finding_through_review_claim(self):
        claim = load_claim({
            "claim_id": "TEST-ICD10-004",
            "payer": "Medicare Part B",
            "npi": "",
            "cpt_codes": ["99213"],
            "icd10_codes": ["J02.0"],
            "modifiers": [],
            "place_of_service": "11",
            "units": {},
        })
        findings = review_claim(claim)
        assert not any(f.rule in ("icd10_invalid", "icd10_unspecified") for f in findings)
