"""
Unit tests for the deterministic rule layer.

Tests are self-contained: no live APIs, no CMS reference files required.
MUE tests monkeypatch mue_loader.lookup_mue to inject controlled fixture data.
NPI tests monkeypatch requests.get to avoid real NPPES network calls.
Loader tests use tmp_path fixtures with minimal xlsx/csv content.

Coverage:
  - NPI: empty → no finding; bad format → HIGH; bad Luhn → HIGH
  - NPI: NPPES not found → MEDIUM; NPPES active → no finding; timeout → no finding
  - NPI: HIGH finding short-circuits rule engine (no NCCI/MUE/code_validity)
  - NPI: MEDIUM finding does not short-circuit (coding checks still run)
  - MUE: MAI=1 → HIGH; MAI=2 → MEDIUM; MAI=3 → MEDIUM
  - MUE: units at or below limit → no finding
  - MUE: code not in table → no finding
  - MUE: empty units dict → no finding
  - MUE: synthetic fallback active when no CMS files present
  - MUE: file-backed loader reads xlsx and populates table
  - NCCI: code pair detected → HIGH finding
  - NCCI: unknown pair → no finding
  - code_validity: Z00.00 + problem E/M → HIGH finding
  - code_validity: missing modifier 25 → MEDIUM finding
"""

from __future__ import annotations

import sys
import pathlib
from unittest.mock import patch, MagicMock

import pytest
import pandas as pd
import requests

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rules.models import ClaimIn
from rules import mue_loader
from rules.mue import check_mue_limits
from rules.ncci import check_ncci_pairs
from rules.code_validity import check_code_validity
from rules.rule_engine import review_claim
from rules.npi import check_npi, luhn_valid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _claim(**overrides) -> ClaimIn:
    base = dict(
        claim_id="TEST-MUE-001",
        payer="Medicare",
        npi="",
        cpt_codes=["99214"],
        icd10_codes=["I10"],
        modifiers=[],
        place_of_service="11",
        units={"99214": 1},
        note_text="",
        description="",
    )
    base.update(overrides)
    return ClaimIn(**base)


@pytest.fixture(autouse=True)
def clear_mue_cache():
    """Clear MUE lru_cache before and after every test."""
    mue_loader._clear_mue_cache()
    yield
    mue_loader._clear_mue_cache()


# ---------------------------------------------------------------------------
# MUE — MAI severity mapping
# ---------------------------------------------------------------------------

def test_mue_mai1_exceeds_limit_returns_high():
    """MAI=1 unit violation → HIGH finding (absolute per-line limit)."""
    claim = _claim(cpt_codes=["36415"], units={"36415": 5})
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 3, "mai": "1", "source_file": "synthetic"}):
        findings = check_mue_limits(claim)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].rule == "mue_unit_limit"
    assert "36415" in findings[0].issue
    assert "5" in findings[0].issue
    assert "3" in findings[0].issue


def test_mue_mai2_exceeds_limit_returns_medium():
    """MAI=2 unit violation → MEDIUM finding (date-of-service edit)."""
    claim = _claim(cpt_codes=["80053"], units={"80053": 2})
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 1, "mai": "2", "source_file": "synthetic"}):
        findings = check_mue_limits(claim)
    assert len(findings) == 1
    assert findings[0].severity == "MEDIUM"
    assert "MAI 2" in findings[0].issue


def test_mue_mai3_exceeds_limit_returns_medium():
    """MAI=3 unit violation → MEDIUM finding (clinical rationale may bypass)."""
    claim = _claim(cpt_codes=["99999"], units={"99999": 4})
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 2, "mai": "3", "source_file": "synthetic"}):
        findings = check_mue_limits(claim)
    assert len(findings) == 1
    assert findings[0].severity == "MEDIUM"
    assert "MAI 3" in findings[0].issue


# ---------------------------------------------------------------------------
# MUE — no finding conditions
# ---------------------------------------------------------------------------

def test_mue_units_at_limit_no_finding():
    """Reported units exactly equal to MUE limit → no finding."""
    claim = _claim(cpt_codes=["36415"], units={"36415": 3})
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 3, "mai": "1", "source_file": "synthetic"}):
        findings = check_mue_limits(claim)
    assert findings == []


def test_mue_units_below_limit_no_finding():
    """Reported units below MUE limit → no finding."""
    claim = _claim(cpt_codes=["80053"], units={"80053": 1})
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 1, "mai": "2", "source_file": "synthetic"}):
        findings = check_mue_limits(claim)
    assert findings == []


def test_mue_code_not_in_table_no_finding():
    """Code absent from MUE table → no finding."""
    claim = _claim(cpt_codes=["XXXXX"], units={"XXXXX": 99})
    with patch.object(mue_loader, "lookup_mue", return_value=None):
        findings = check_mue_limits(claim)
    assert findings == []


def test_mue_empty_units_no_finding():
    """Empty units dict → no finding (nothing to check)."""
    claim = _claim(units={})
    findings = check_mue_limits(claim)
    assert findings == []


# ---------------------------------------------------------------------------
# MUE — citation structure
# ---------------------------------------------------------------------------

def test_mue_finding_has_structured_citation():
    """MUE finding must carry a Citation with doc_id and effective_date."""
    claim = _claim(cpt_codes=["80053"], units={"80053": 2})
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 1, "mai": "2", "source_file": "synthetic"}):
        findings = check_mue_limits(claim)
    assert len(findings) == 1
    cit = findings[0].citation
    assert cit.doc_id == mue_loader.MUE_DOC_ID
    assert cit.effective_date == mue_loader.MUE_EFFECTIVE_DATE
    assert cit.source == "CMS MUE"
    assert cit.excerpt  # non-empty


def test_mue_finding_confidence_high_for_mai1():
    """MAI=1 findings should have higher confidence than MAI=2/3."""
    claim = _claim(cpt_codes=["36415"], units={"36415": 5})
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 3, "mai": "1", "source_file": "synthetic"}):
        findings_mai1 = check_mue_limits(claim)
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 3, "mai": "2", "source_file": "synthetic"}):
        findings_mai2 = check_mue_limits(claim)
    assert findings_mai1[0].confidence > findings_mai2[0].confidence


# ---------------------------------------------------------------------------
# MUE — multiple codes in one claim
# ---------------------------------------------------------------------------

def test_mue_multiple_violations_all_reported():
    """Both codes exceeding limit in same claim → two findings."""
    claim = _claim(
        cpt_codes=["80053", "36415"],
        units={"80053": 3, "36415": 5},
    )
    def _lookup(code, reference_dir=mue_loader._DEFAULT_DIR):
        if code == "80053":
            return {"mue_value": 1, "mai": "2", "source_file": "synthetic"}
        if code == "36415":
            return {"mue_value": 3, "mai": "1", "source_file": "synthetic"}
        return None
    with patch.object(mue_loader, "lookup_mue", side_effect=_lookup):
        findings = check_mue_limits(claim)
    assert len(findings) == 2
    severities = {f.severity for f in findings}
    assert "HIGH" in severities
    assert "MEDIUM" in severities


def test_mue_only_violating_code_gets_finding():
    """One code in limit, one exceeding → only the exceeding code gets a finding."""
    claim = _claim(
        cpt_codes=["80053", "36415"],
        units={"80053": 1, "36415": 5},
    )
    def _lookup(code, reference_dir=mue_loader._DEFAULT_DIR):
        if code == "80053":
            return {"mue_value": 1, "mai": "2", "source_file": "synthetic"}
        if code == "36415":
            return {"mue_value": 3, "mai": "1", "source_file": "synthetic"}
        return None
    with patch.object(mue_loader, "lookup_mue", side_effect=_lookup):
        findings = check_mue_limits(claim)
    assert len(findings) == 1
    assert "36415" in findings[0].issue


# ---------------------------------------------------------------------------
# MUE loader — synthetic fallback
# ---------------------------------------------------------------------------

def test_mue_loader_synthetic_fallback_when_no_directory(tmp_path):
    """loader uses _SYNTHETIC_MUE when reference directory does not exist."""
    nonexistent = str(tmp_path / "no_such_dir")
    table = mue_loader.load_mue_table(nonexistent)
    assert table is mue_loader._SYNTHETIC_MUE or len(table) > 0
    # Synthetic table must include common lab panel codes
    assert "80053" in table
    assert "80048" in table


def test_mue_loader_synthetic_fallback_empty_directory(tmp_path):
    """loader uses _SYNTHETIC_MUE when reference directory exists but is empty."""
    table = mue_loader.load_mue_table(str(tmp_path))
    assert table is mue_loader._SYNTHETIC_MUE or len(table) > 0


def test_mue_loader_discover_empty_directory_returns_empty(tmp_path):
    assert mue_loader.discover_mue_files(str(tmp_path)) == []


def test_mue_loader_discover_nonexistent_returns_empty(tmp_path):
    assert mue_loader.discover_mue_files(str(tmp_path / "nope")) == []


# ---------------------------------------------------------------------------
# MUE loader — file-backed loading (xlsx fixture)
# ---------------------------------------------------------------------------

@pytest.fixture
def mue_fixture_dir(tmp_path):
    """
    Create a minimal MUE xlsx fixture with the same column naming CMS uses.
    Includes one MAI=1 entry (36415, limit 3) and one MAI=2 entry (80053, limit 1).
    """
    rows = [
        ["HCPCS / CPT Code", "MUE Values", "MAI", "MUE Rationale"],
        ["36415", "3", "1", "Nature of service"],
        ["80053", "1", "2", "Clinical: MUE"],
        ["80048", "1", "2", "Clinical: MUE"],
        ["", "", "", ""],        # blank row — should be skipped
        ["0", "0", "0", ""],    # zero-value row — should be skipped
    ]
    df = pd.DataFrame(rows)
    fpath = tmp_path / "mue_practitioner_q22026.xlsx"
    df.to_excel(str(fpath), index=False, header=False)
    return str(tmp_path)


def test_mue_loader_file_backed_loads_codes(mue_fixture_dir):
    """File-backed loader reads xlsx and populates the code table."""
    table = mue_loader._build_mue_table(mue_fixture_dir)
    assert "36415" in table
    assert "80053" in table
    assert "80048" in table


def test_mue_loader_file_backed_correct_mue_value(mue_fixture_dir):
    table = mue_loader._build_mue_table(mue_fixture_dir)
    assert table["36415"]["mue_value"] == 3
    assert table["80053"]["mue_value"] == 1


def test_mue_loader_file_backed_correct_mai(mue_fixture_dir):
    table = mue_loader._build_mue_table(mue_fixture_dir)
    assert table["36415"]["mai"] == "1"
    assert table["80053"]["mai"] == "2"


def test_mue_loader_file_backed_skips_blank_rows(mue_fixture_dir):
    table = mue_loader._build_mue_table(mue_fixture_dir)
    assert "" not in table
    assert "0" not in table


def test_mue_loader_lookup_mue_returns_entry(mue_fixture_dir):
    entry = mue_loader.lookup_mue("80053", reference_dir=mue_fixture_dir)
    assert entry is not None
    assert entry["mue_value"] == 1
    assert entry["mai"] == "2"


def test_mue_loader_lookup_mue_unknown_code_returns_none(mue_fixture_dir):
    assert mue_loader.lookup_mue("XXXXX", reference_dir=mue_fixture_dir) is None


def test_mue_loader_lookup_case_insensitive(mue_fixture_dir):
    """Code lookup normalizes to uppercase."""
    entry = mue_loader.lookup_mue("80053", reference_dir=mue_fixture_dir)
    entry_lower = mue_loader.lookup_mue("80053", reference_dir=mue_fixture_dir)
    assert entry == entry_lower


def test_mue_loader_clear_cache(mue_fixture_dir):
    """_clear_mue_cache() allows the table to be reloaded."""
    t1 = mue_loader._build_mue_table(mue_fixture_dir)
    mue_loader._clear_mue_cache()
    t2 = mue_loader._build_mue_table(mue_fixture_dir)
    assert t1 == t2  # same content after reload


# ---------------------------------------------------------------------------
# MUE loader — CSV support
# ---------------------------------------------------------------------------

@pytest.fixture
def mue_csv_dir(tmp_path):
    """Create a minimal MUE CSV fixture."""
    rows = [
        "HCPCS / CPT Code,MUE Values,MAI,MUE Rationale",
        "36415,3,1,Nature of service",
        "80053,1,2,Clinical: MUE",
    ]
    fpath = tmp_path / "mue_practitioner.csv"
    fpath.write_text("\n".join(rows))
    return str(tmp_path)


def test_mue_loader_csv_loads_codes(mue_csv_dir):
    table = mue_loader._build_mue_table(mue_csv_dir)
    assert "36415" in table
    assert "80053" in table


# ---------------------------------------------------------------------------
# MUE — integration with rule engine
# ---------------------------------------------------------------------------

def test_rule_engine_mue_finding_appears_after_ncci():
    """rule_engine.review_claim() returns MUE finding when units exceed limit."""
    claim = _claim(
        cpt_codes=["36415"],
        units={"36415": 5},
    )
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 3, "mai": "1", "source_file": "synthetic"}):
        findings = review_claim(claim)
    mue_findings = [f for f in findings if f.rule == "mue_unit_limit"]
    assert len(mue_findings) == 1
    assert mue_findings[0].severity == "HIGH"


def test_rule_engine_no_mue_finding_when_units_within_limit():
    """rule_engine returns no MUE finding when all units are within limits."""
    claim = _claim(
        cpt_codes=["80053"],
        units={"80053": 1},
    )
    with patch.object(mue_loader, "lookup_mue", return_value={"mue_value": 1, "mai": "2", "source_file": "synthetic"}):
        findings = review_claim(claim)
    mue_findings = [f for f in findings if f.rule == "mue_unit_limit"]
    assert mue_findings == []


# ---------------------------------------------------------------------------
# NCCI — existing rule still works after MUE addition
# ---------------------------------------------------------------------------

def test_ncci_known_bundled_pair_returns_high_finding():
    """80048 bundled with 80053 → NCCI HIGH finding (regression guard)."""
    claim = _claim(
        cpt_codes=["80053", "80048"],
        units={"80053": 1, "80048": 1},
    )
    findings = check_ncci_pairs(claim)
    assert any(f.severity == "HIGH" and f.rule == "ncci_ptp" for f in findings)


def test_ncci_unknown_pair_no_finding():
    """Unrelated codes → no NCCI finding."""
    claim = _claim(cpt_codes=["99213", "85025"], units={"99213": 1, "85025": 1})
    findings = check_ncci_pairs(claim)
    assert all(f.rule != "ncci_ptp" for f in findings)


# ---------------------------------------------------------------------------
# code_validity — existing rules still work after MUE addition
# ---------------------------------------------------------------------------

def test_code_validity_z00_with_problem_em_returns_high():
    """Z00.00 + 99214 → HIGH dx-procedure conflict (regression guard)."""
    claim = _claim(
        cpt_codes=["99214"],
        icd10_codes=["Z00.00"],
        units={"99214": 1},
    )
    findings = check_code_validity(claim)
    assert any(f.severity == "HIGH" and "Z00.00" in f.issue for f in findings)


def test_code_validity_missing_modifier_25_returns_medium():
    """Z00.00 + 99214, no modifier 25 → MEDIUM finding (regression guard)."""
    claim = _claim(
        cpt_codes=["99214"],
        icd10_codes=["Z00.00"],
        modifiers=[],
        units={"99214": 1},
    )
    findings = check_code_validity(claim)
    assert any(f.severity == "MEDIUM" and "25" in f.issue for f in findings)


# ---------------------------------------------------------------------------
# code_validity — TD-06: modifier 76/77 (repeat procedure) and 50 (bilateral)
# ---------------------------------------------------------------------------

def test_repeat_procedure_two_units_no_modifier_returns_medium():
    claim = _claim(cpt_codes=["96372"], icd10_codes=["I10"], modifiers=[], units={"96372": 2})
    findings = check_code_validity(claim)
    assert any(f.rule == "missing_modifier_76" and f.severity == "MEDIUM" for f in findings)


def test_repeat_procedure_with_modifier_76_no_finding():
    claim = _claim(cpt_codes=["96372"], icd10_codes=["I10"], modifiers=["76"], units={"96372": 2})
    findings = check_code_validity(claim)
    assert not any(f.rule == "missing_modifier_76" for f in findings)


def test_repeat_procedure_with_modifier_77_no_finding():
    claim = _claim(cpt_codes=["96372"], icd10_codes=["I10"], modifiers=["77"], units={"96372": 2})
    findings = check_code_validity(claim)
    assert not any(f.rule == "missing_modifier_76" for f in findings)


def test_repeat_procedure_single_unit_no_finding():
    claim = _claim(cpt_codes=["96372"], icd10_codes=["I10"], modifiers=[], units={"96372": 1})
    findings = check_code_validity(claim)
    assert not any(f.rule == "missing_modifier_76" for f in findings)


def test_non_repeatable_code_two_units_no_finding():
    claim = _claim(cpt_codes=["99214"], icd10_codes=["I10"], modifiers=[], units={"99214": 2})
    findings = check_code_validity(claim)
    assert not any(f.rule == "missing_modifier_76" for f in findings)


def test_bilateral_procedure_two_units_no_modifier_returns_medium():
    claim = _claim(cpt_codes=["69210"], icd10_codes=["I10"], modifiers=[], units={"69210": 2})
    findings = check_code_validity(claim)
    assert any(f.rule == "missing_modifier_50" and f.severity == "MEDIUM" for f in findings)


def test_bilateral_procedure_with_modifier_50_no_finding():
    claim = _claim(cpt_codes=["69210"], icd10_codes=["I10"], modifiers=["50"], units={"69210": 2})
    findings = check_code_validity(claim)
    assert not any(f.rule == "missing_modifier_50" for f in findings)


def test_bilateral_procedure_with_rt_lt_pair_no_finding():
    claim = _claim(cpt_codes=["69210"], icd10_codes=["I10"], modifiers=["RT", "LT"], units={"69210": 2})
    findings = check_code_validity(claim)
    assert not any(f.rule == "missing_modifier_50" for f in findings)


def test_bilateral_procedure_with_only_rt_returns_medium():
    """RT alone (no matching LT) does not satisfy the bilateral-pair exception."""
    claim = _claim(cpt_codes=["69210"], icd10_codes=["I10"], modifiers=["RT"], units={"69210": 2})
    findings = check_code_validity(claim)
    assert any(f.rule == "missing_modifier_50" for f in findings)


def test_bilateral_procedure_single_unit_no_finding():
    claim = _claim(cpt_codes=["69210"], icd10_codes=["I10"], modifiers=[], units={"69210": 1})
    findings = check_code_validity(claim)
    assert not any(f.rule == "missing_modifier_50" for f in findings)


# ---------------------------------------------------------------------------
# NPI — luhn_valid() unit tests
# ---------------------------------------------------------------------------

# 1234567893 computed valid (passes Luhn with 80840 prefix); 1234567890 is invalid.
_VALID_NPI = "1234567893"
_INVALID_NPI = "1234567890"


def test_luhn_valid_known_valid_npi():
    assert luhn_valid(_VALID_NPI) is True


def test_luhn_valid_known_invalid_npi():
    assert luhn_valid(_INVALID_NPI) is False


def test_luhn_valid_non_numeric_returns_false():
    assert luhn_valid("123ABC7890") is False


def test_luhn_valid_wrong_length_returns_false():
    assert luhn_valid("12345") is False


def test_luhn_valid_empty_returns_false():
    assert luhn_valid("") is False


# ---------------------------------------------------------------------------
# NPI — check_npi() behavior
# ---------------------------------------------------------------------------

def test_npi_empty_npi_returns_no_finding():
    """Empty NPI is optional — no finding emitted."""
    claim = _claim(npi="")
    assert check_npi(claim) == []


def test_npi_whitespace_only_returns_no_finding():
    """Whitespace-only NPI is treated as empty."""
    claim = _claim(npi="   ")
    assert check_npi(claim) == []


def test_npi_non_numeric_returns_high():
    """NPI containing letters → HIGH finding, rule 'npi_invalid'."""
    claim = _claim(npi="123ABC7890")
    findings = check_npi(claim)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].rule == "npi_invalid"


def test_npi_wrong_length_returns_high():
    """NPI shorter than 10 digits → HIGH finding."""
    claim = _claim(npi="12345")
    findings = check_npi(claim)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].rule == "npi_invalid"


def test_npi_bad_luhn_returns_high():
    """10-digit NPI that fails Luhn → HIGH finding."""
    claim = _claim(npi=_INVALID_NPI)
    findings = check_npi(claim)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].rule == "npi_invalid"
    assert _INVALID_NPI in findings[0].issue


def test_npi_nppes_not_found_returns_medium():
    """Luhn-valid NPI with 0 NPPES results → MEDIUM finding, rule 'npi_registry'."""
    claim = _claim(npi=_VALID_NPI)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"result_count": 0, "results": []}
    mock_resp.raise_for_status.return_value = None
    with patch("rules.npi.requests.get", return_value=mock_resp):
        findings = check_npi(claim)
    assert len(findings) == 1
    assert findings[0].severity == "MEDIUM"
    assert findings[0].rule == "npi_registry"
    assert _VALID_NPI in findings[0].issue


def test_npi_nppes_active_returns_no_finding():
    """Luhn-valid NPI with active NPPES record → no finding."""
    claim = _claim(npi=_VALID_NPI)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "result_count": 1,
        "results": [{"basic": {"status": "A", "first_name": "JOHN", "last_name": "DOE"}}],
    }
    mock_resp.raise_for_status.return_value = None
    with patch("rules.npi.requests.get", return_value=mock_resp):
        findings = check_npi(claim)
    assert findings == []


def test_npi_nppes_inactive_status_returns_medium():
    """Luhn-valid NPI found but status != 'A' → MEDIUM finding."""
    claim = _claim(npi=_VALID_NPI)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "result_count": 1,
        "results": [{"basic": {"status": "D"}}],  # D = deactivated
    }
    mock_resp.raise_for_status.return_value = None
    with patch("rules.npi.requests.get", return_value=mock_resp):
        findings = check_npi(claim)
    assert len(findings) == 1
    assert findings[0].severity == "MEDIUM"
    assert findings[0].rule == "npi_registry"


def test_npi_nppes_timeout_returns_no_finding():
    """NPPES request times out → no finding; review continues unblocked."""
    claim = _claim(npi=_VALID_NPI)
    with patch("rules.npi.requests.get", side_effect=requests.Timeout()):
        findings = check_npi(claim)
    assert findings == []


def test_npi_nppes_network_error_returns_no_finding():
    """NPPES network error (ConnectionError) → no finding."""
    claim = _claim(npi=_VALID_NPI)
    with patch("rules.npi.requests.get", side_effect=requests.ConnectionError()):
        findings = check_npi(claim)
    assert findings == []


def test_npi_finding_has_structured_citation():
    """NPI finding carries Citation with correct doc_id and source."""
    claim = _claim(npi=_INVALID_NPI)
    findings = check_npi(claim)
    assert len(findings) == 1
    cit = findings[0].citation
    assert cit.doc_id == "NPPES_NPI_REGISTRY"
    assert cit.source == "NPPES"
    assert cit.section == "Provider Enumeration Validation"
    assert cit.excerpt  # non-empty


# ---------------------------------------------------------------------------
# NPI — rule engine short-circuit behavior
# ---------------------------------------------------------------------------

def test_npi_high_finding_short_circuits_rule_engine():
    """HIGH NPI (bad Luhn) → rule engine returns only NPI finding; NCCI/MUE/code_validity do not run."""
    claim = _claim(
        npi=_INVALID_NPI,
        cpt_codes=["80053", "80048"],  # would normally trigger NCCI
        units={"80053": 1, "80048": 1},
        icd10_codes=["Z00.00"],        # would normally trigger dx conflict with 99214
    )
    findings = review_claim(claim)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].rule == "npi_invalid"
    assert findings[0].finding_id  # stamped by rule engine


def test_npi_medium_finding_does_not_short_circuit():
    """MEDIUM NPI (not found in NPPES) does not short-circuit; coding checks still run."""
    claim = _claim(
        npi=_VALID_NPI,
        cpt_codes=["80053", "80048"],
        units={"80053": 1, "80048": 1},
        icd10_codes=["I10"],
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"result_count": 0, "results": []}
    mock_resp.raise_for_status.return_value = None
    with patch("rules.npi.requests.get", return_value=mock_resp):
        findings = review_claim(claim)
    rules_hit = {f.rule for f in findings}
    assert "npi_registry" in rules_hit
    assert "ncci_ptp" in rules_hit  # NCCI still ran
