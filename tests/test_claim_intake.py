"""
Tests for app/claim_intake.py — all deterministic, no Streamlit, no LLM, no live APIs.
"""

import pytest
import sys
import pathlib

# Ensure repo root is on sys.path so `app`, `rules`, `db` are importable.
_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.claim_intake import (
    PAYER_ID_MAP,
    WORKED_EXAMPLE,
    get_payer_id,
    validate_npi,
    normalize_code,
    build_manual_claim,
)
from rules.rule_engine import load_claim, review_claim, overall_risk


# ---------------------------------------------------------------------------
# get_payer_id
# ---------------------------------------------------------------------------

def test_get_payer_id_known_medicare():
    assert get_payer_id("Medicare") == "MEDICARE"


def test_get_payer_id_known_bcbs():
    assert get_payer_id("Blue Cross Blue Shield (BCBS)") == "BCBS"


def test_get_payer_id_unknown_returns_empty():
    assert get_payer_id("Foobar Insurance Co") == ""


def test_get_payer_id_commercial_other_returns_empty():
    assert get_payer_id("Commercial - Other") == ""


# ---------------------------------------------------------------------------
# validate_npi
# ---------------------------------------------------------------------------

def test_validate_npi_empty_is_valid():
    ok, msg = validate_npi("")
    assert ok is True
    assert msg == ""


def test_validate_npi_ten_digits_is_valid():
    ok, msg = validate_npi("1234567890")
    assert ok is True
    assert msg == ""


def test_validate_npi_non_digit_is_invalid():
    ok, msg = validate_npi("123ABC7890")
    assert ok is False
    assert msg  # non-empty error


def test_validate_npi_too_short_is_invalid():
    ok, msg = validate_npi("12345")
    assert ok is False
    assert "10" in msg


def test_validate_npi_too_long_is_invalid():
    ok, msg = validate_npi("12345678901")
    assert ok is False
    assert "10" in msg


# ---------------------------------------------------------------------------
# normalize_code
# ---------------------------------------------------------------------------

def test_normalize_code_strips_whitespace():
    assert normalize_code("  99213  ") == "99213"


def test_normalize_code_uppercases():
    assert normalize_code("z00.00") == "Z00.00"


def test_normalize_code_empty_stays_empty():
    assert normalize_code("") == ""


# ---------------------------------------------------------------------------
# build_manual_claim — structure and normalization
# ---------------------------------------------------------------------------

def _header(**overrides) -> dict:
    base = {
        "claim_id": "CLM-T-001",
        "payer_name": "Medicare",
        "payer_id": "",
        "npi": "",
        "provider_specialty": "Internal Medicine",
        "note_text": "",
    }
    base.update(overrides)
    return base


def _line(cpt="99213", icd10_1="J06.9", **overrides) -> dict:
    base = {
        "cpt": cpt, "mod1": "", "mod2": "", "units": 1,
        "icd10_1": icd10_1, "icd10_2": "", "icd10_3": "", "icd10_4": "",
    }
    base.update(overrides)
    return base


def test_build_manual_claim_basic_structure():
    result = build_manual_claim(_header(), [_line()])
    assert result["claim_id"] == "CLM-T-001"
    assert result["payer_name"] == "Medicare"
    assert result["cpt_codes"] == ["99213"]
    assert result["icd10_codes"] == ["J06.9"]
    assert result["modifiers"] == []
    assert "service_lines" in result


def test_build_manual_claim_payer_id_auto_populated():
    result = build_manual_claim(_header(payer_id=""), [_line()])
    assert result["payer_id"] == "MEDICARE"


def test_build_manual_claim_payer_id_explicit_overrides_map():
    result = build_manual_claim(_header(payer_id="CUSTOM-123"), [_line()])
    assert result["payer_id"] == "CUSTOM-123"


def test_build_manual_claim_cpt_normalized_to_uppercase():
    result = build_manual_claim(_header(), [_line(cpt="99213")])
    assert "99213" in result["cpt_codes"]


def test_build_manual_claim_icd10_normalized():
    result = build_manual_claim(_header(), [_line(icd10_1="  z00.00  ")])
    assert "Z00.00" in result["icd10_codes"]


def test_build_manual_claim_deduplicates_cpt_across_lines():
    lines = [_line(cpt="99213"), _line(cpt="99213")]
    result = build_manual_claim(_header(), lines)
    assert result["cpt_codes"].count("99213") == 1


def test_build_manual_claim_deduplicates_icd10_across_lines():
    lines = [_line(icd10_1="J06.9"), _line(icd10_1="J06.9")]
    result = build_manual_claim(_header(), lines)
    assert result["icd10_codes"].count("J06.9") == 1


def test_build_manual_claim_blank_cpt_lines_excluded():
    lines = [_line(cpt=""), _line(cpt="99213")]
    result = build_manual_claim(_header(), lines)
    assert "" not in result["cpt_codes"]
    assert "99213" in result["cpt_codes"]


def test_build_manual_claim_modifiers_collected_from_mod1_and_mod2():
    lines = [_line(mod1="25", mod2="59")]
    result = build_manual_claim(_header(), lines)
    assert "25" in result["modifiers"]
    assert "59" in result["modifiers"]


def test_build_manual_claim_empty_claim_id_defaults():
    result = build_manual_claim(_header(claim_id=""), [_line()])
    assert result["claim_id"] == "CLM-MANUAL"


def test_build_manual_claim_service_lines_preserved():
    lines = [_line(cpt="99214"), _line(cpt="80053")]
    result = build_manual_claim(_header(), lines)
    assert len(result["service_lines"]) == 2
    assert result["service_lines"][0]["cpt"] == "99214"


def test_build_manual_claim_backward_compat_payer_key():
    result = build_manual_claim(_header(payer_name="Aetna"), [_line()])
    assert result["payer"] == "Aetna"


# ---------------------------------------------------------------------------
# Integration: manual claim through rule engine
# ---------------------------------------------------------------------------

def test_manual_claim_loads_without_error():
    claim_dict = build_manual_claim(_header(), [_line()])
    claim = load_claim(claim_dict)
    assert claim.claim_id == "CLM-T-001"
    assert claim.payer == "Medicare"


def test_manual_claim_worked_example_produces_ncci_finding():
    """The WORKED_EXAMPLE (80048 + 80053) must trigger an NCCI HIGH finding."""
    lines = WORKED_EXAMPLE["service_lines"]
    header = {
        "claim_id": WORKED_EXAMPLE["claim_id"],
        "payer_name": WORKED_EXAMPLE["payer_name"],
        "payer_id": "",
        "npi": WORKED_EXAMPLE["npi"],
        "provider_specialty": WORKED_EXAMPLE["provider_specialty"],
        "note_text": WORKED_EXAMPLE["note_text"],
    }
    claim_dict = build_manual_claim(header, lines)
    claim = load_claim(claim_dict)
    findings = review_claim(claim)
    ncci = [f for f in findings if f.rule == "ncci_ptp"]
    assert ncci, "Expected NCCI PTP finding from worked example"
    assert ncci[0].severity == "HIGH"


def test_manual_claim_overall_risk_high_for_worked_example():
    lines = WORKED_EXAMPLE["service_lines"]
    header = {
        "claim_id": WORKED_EXAMPLE["claim_id"],
        "payer_name": WORKED_EXAMPLE["payer_name"],
        "payer_id": "",
        "npi": "",
        "provider_specialty": "",
        "note_text": "",
    }
    claim_dict = build_manual_claim(header, lines)
    findings = review_claim(load_claim(claim_dict))
    assert overall_risk(findings) == "HIGH"


def test_manual_claim_finding_ids_stable():
    """Same manual claim must produce the same finding_ids across runs."""
    lines = [_line(cpt="80053"), _line(cpt="80048", icd10_1="I10")]
    header = _header(claim_id="CLM-STABLE")
    claim_dict = build_manual_claim(header, lines)
    run1 = review_claim(load_claim(claim_dict))
    run2 = review_claim(load_claim(claim_dict))
    assert run1[0].finding_id == run2[0].finding_id


# ---------------------------------------------------------------------------
# Units propagation
# ---------------------------------------------------------------------------

def test_build_manual_claim_units_default_to_1():
    """Service line without explicit units → units[cpt] == 1."""
    line = {"cpt": "99213", "mod1": "", "mod2": "",
            "icd10_1": "J06.9", "icd10_2": "", "icd10_3": "", "icd10_4": ""}
    result = build_manual_claim(_header(), [line])
    assert result["units"]["99213"] == 1


def test_build_manual_claim_explicit_units_propagated():
    """Explicit units value carried through to claim dict."""
    result = build_manual_claim(_header(), [_line(cpt="36415", units=3)])
    assert result["units"]["36415"] == 3


def test_build_manual_claim_units_only_for_non_blank_cpt():
    """Blank CPT lines must not appear in units dict."""
    lines = [_line(cpt="", units=5), _line(cpt="99213", units=2)]
    result = build_manual_claim(_header(), lines)
    assert "" not in result["units"]
    assert result["units"]["99213"] == 2


def test_build_manual_claim_dedup_units_first_line_wins():
    """When same CPT appears on two lines, first-seen units value is used."""
    lines = [_line(cpt="99213", units=1), _line(cpt="99213", units=5)]
    result = build_manual_claim(_header(), lines)
    assert result["units"]["99213"] == 1


def test_build_manual_claim_multiple_cpts_each_get_units():
    """Different CPTs on different lines each get their own units entry."""
    lines = [_line(cpt="99214", units=1), _line(cpt="80053", units=2)]
    result = build_manual_claim(_header(), lines)
    assert result["units"]["99214"] == 1
    assert result["units"]["80053"] == 2


def test_build_manual_claim_units_passed_to_load_claim():
    """Units from build_manual_claim() must survive load_claim() round-trip."""
    result = build_manual_claim(_header(), [_line(cpt="36415", units=3)])
    claim = load_claim(result)
    assert claim.units["36415"] == 3


def test_worked_example_has_units():
    """WORKED_EXAMPLE service lines all have a 'units' key."""
    for line in WORKED_EXAMPLE["service_lines"]:
        assert "units" in line, f"Service line missing 'units': {line}"


def test_worked_example_units_are_positive():
    """WORKED_EXAMPLE units are positive integers."""
    for line in WORKED_EXAMPLE["service_lines"]:
        assert isinstance(line["units"], int)
        assert line["units"] >= 1
