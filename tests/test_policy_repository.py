"""
Tests for Sprint 3 policy intelligence layer.

Covers:
  - policy_examples.json loads successfully
  - lookup by document_id
  - each current rule finding citation resolves to a policy reference
  - find_policies_by_codes matches expected entries
  - get_citation_detail returns expected fields
  - audit save works with citation_effective_date
"""

import dataclasses
import json
import pathlib

import pytest

from retrieval.policy_repository import (
    find_policies_by_codes,
    find_policy_by_document_id,
    get_citation_detail,
    load_policy_references,
)
from rules.models import Citation, ClaimIn
from rules import ncci, code_validity
from rules.rule_engine import load_claim, review_claim
from db.audit_repository import AuditDecision, AuditRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

POLICY_FILE = (
    pathlib.Path(__file__).parent.parent / "data" / "reference" / "policy_examples.json"
)

KNOWN_DOC_IDS = [
    "NCCI_PTP_80048_80053_SAMPLE",
    "ICD10_Z00_PREVENTIVE_CONTEXT_SAMPLE",
    "NCCI_MODIFIER_25_SAMPLE",
]

REQUIRED_FIELDS = {
    "document_id", "source_type", "title", "section",
    "effective_date", "edition", "excerpt", "applies_to_codes", "notes",
}

_CLM001 = {
    "claim_id": "CLM-001",
    "payer": "Medicare Part B",
    "npi": "",
    "cpt_codes": ["99214", "80053", "80048", "36415"],
    "icd10_codes": ["Z00.00"],
    "modifiers": [],
    "place_of_service": "11",
    "units": {},
}

_CLM004 = {
    "claim_id": "CLM-004",
    "payer": "Medicare Part B",
    "npi": "",
    "cpt_codes": ["99214"],
    "icd10_codes": ["Z00.00"],
    "modifiers": [],
    "place_of_service": "11",
    "units": {},
}


@pytest.fixture
def repo(tmp_path):
    r = AuditRepository(db_path=tmp_path / "test_sprint3.db")
    r.initialize_database()
    return r


def _make_decision(**overrides) -> AuditDecision:
    base = AuditDecision(
        claim_id="CLM-001",
        finding_id="abc123def456",
        source="rule_layer",
        severity="HIGH",
        issue="Bundled code pair: 80048 is a component of 80053",
        recommendation="Remove 80048 when billed with 80053.",
        citation_source="NCCI PTP",
        citation_doc_id="NCCI_PTP_80048_80053_SAMPLE",
        citation_section="Physician/Practitioner PTP Edit Table, Column 1 / Column 2",
        citation_edition="NCCI Policy Manual for Medicare Services (sample reference)",
        citation_effective_date="2000-01-01",
        confidence=0.95,
        user_decision="accepted",
        override_reason="",
        reviewer_name="Dr. Test",
        model_version="rule_layer_v0.1",
        prompt_version="n/a",
    )
    return dataclasses.replace(base, **overrides)


# ---------------------------------------------------------------------------
# policy_examples.json structure
# ---------------------------------------------------------------------------

def test_policy_file_exists():
    """data/reference/policy_examples.json must exist."""
    assert POLICY_FILE.exists(), f"Policy file not found: {POLICY_FILE}"


def test_policy_file_is_valid_json():
    """policy_examples.json must parse as a JSON array."""
    with open(POLICY_FILE) as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) > 0


def test_policy_entries_have_required_fields():
    """Every policy entry must contain all required fields."""
    policies = load_policy_references()
    for policy in policies:
        missing = REQUIRED_FIELDS - set(policy.keys())
        assert not missing, f"Policy {policy.get('document_id')} missing fields: {missing}"


def test_all_known_doc_ids_present():
    """The three core doc_ids used by rule modules must be present in the file."""
    doc_ids = {p["document_id"] for p in load_policy_references()}
    for doc_id in KNOWN_DOC_IDS:
        assert doc_id in doc_ids, f"Missing expected document_id: {doc_id}"


# ---------------------------------------------------------------------------
# find_policy_by_document_id
# ---------------------------------------------------------------------------

def test_find_by_document_id_returns_correct_entry():
    policy = find_policy_by_document_id("NCCI_PTP_80048_80053_SAMPLE")
    assert policy is not None
    assert policy["document_id"] == "NCCI_PTP_80048_80053_SAMPLE"
    assert "80048" in policy["applies_to_codes"]
    assert "80053" in policy["applies_to_codes"]


def test_find_by_document_id_returns_none_for_unknown():
    assert find_policy_by_document_id("DOES_NOT_EXIST") is None


def test_find_icd10_policy_by_document_id():
    policy = find_policy_by_document_id("ICD10_Z00_PREVENTIVE_CONTEXT_SAMPLE")
    assert policy is not None
    assert policy["source_type"] == "ICD10"
    assert "Z00.00" in policy["applies_to_codes"]


def test_find_modifier25_policy_by_document_id():
    policy = find_policy_by_document_id("NCCI_MODIFIER_25_SAMPLE")
    assert policy is not None
    assert policy["source_type"] == "NCCI_POLICY_MANUAL"
    assert "25" in policy["applies_to_codes"]


# ---------------------------------------------------------------------------
# find_policies_by_codes
# ---------------------------------------------------------------------------

def test_find_by_cpt_code_returns_matching_policies():
    results = find_policies_by_codes(cpt_codes=["80048"])
    doc_ids = {p["document_id"] for p in results}
    assert "NCCI_PTP_80048_80053_SAMPLE" in doc_ids


def test_find_by_icd10_code_returns_matching_policy():
    results = find_policies_by_codes(icd10_codes=["Z00.00"])
    doc_ids = {p["document_id"] for p in results}
    assert "ICD10_Z00_PREVENTIVE_CONTEXT_SAMPLE" in doc_ids


def test_find_by_modifier_returns_modifier_policy():
    results = find_policies_by_codes(modifiers=["25"])
    doc_ids = {p["document_id"] for p in results}
    assert "NCCI_MODIFIER_25_SAMPLE" in doc_ids


def test_find_by_empty_codes_returns_empty_list():
    assert find_policies_by_codes() == []


# ---------------------------------------------------------------------------
# get_citation_detail
# ---------------------------------------------------------------------------

def test_get_citation_detail_returns_full_policy():
    citation = Citation(
        source="NCCI PTP",
        doc_id="NCCI_PTP_80048_80053_SAMPLE",
        section="Column 1 / Column 2",
        edition="sample",
        effective_date="2000-01-01",
    )
    detail = get_citation_detail(citation)
    assert detail is not None
    assert detail["title"] == "NCCI PTP Edit — Comprehensive Metabolic Panel and Basic Metabolic Panel"
    assert detail["source_url"] is not None
    assert detail["notes"] is not None


def test_get_citation_detail_returns_none_for_unknown_doc_id():
    citation = Citation(
        source="Unknown",
        doc_id="NONEXISTENT_DOC",
        section="n/a",
        edition="n/a",
    )
    assert get_citation_detail(citation) is None


# ---------------------------------------------------------------------------
# Each finding citation resolves to a policy reference
# ---------------------------------------------------------------------------

def test_ncci_finding_citation_resolves():
    """The NCCI bundling finding must have a doc_id that resolves in the policy repo."""
    claim = load_claim(_CLM001)
    findings = review_claim(claim)
    ncci_findings = [f for f in findings if f.rule == "ncci_ptp"]
    assert ncci_findings, "Expected at least one NCCI PTP finding for CLM-001"
    for f in ncci_findings:
        policy = find_policy_by_document_id(f.citation.doc_id)
        assert policy is not None, f"Citation doc_id '{f.citation.doc_id}' not found in policy_examples.json"


def test_dx_conflict_finding_citation_resolves():
    """The dx-procedure conflict finding must have a doc_id that resolves in the policy repo."""
    claim = load_claim(_CLM004)
    findings = review_claim(claim)
    dx_findings = [f for f in findings if f.rule == "dx_procedure_conflict"]
    assert dx_findings, "Expected at least one dx_procedure_conflict finding for CLM-004"
    for f in dx_findings:
        policy = find_policy_by_document_id(f.citation.doc_id)
        assert policy is not None, f"Citation doc_id '{f.citation.doc_id}' not found in policy_examples.json"


def test_modifier25_finding_citation_resolves():
    """The missing modifier 25 finding must have a doc_id that resolves in the policy repo."""
    claim = load_claim(_CLM004)
    findings = review_claim(claim)
    mod_findings = [f for f in findings if f.rule == "missing_modifier_25"]
    assert mod_findings, "Expected at least one missing_modifier_25 finding for CLM-004"
    for f in mod_findings:
        policy = find_policy_by_document_id(f.citation.doc_id)
        assert policy is not None, f"Citation doc_id '{f.citation.doc_id}' not found in policy_examples.json"


# ---------------------------------------------------------------------------
# Audit save with citation_effective_date (Sprint 3 schema addition)
# ---------------------------------------------------------------------------

def test_audit_save_with_effective_date(repo):
    """Audit save must persist citation_effective_date when provided."""
    repo.save_decision(_make_decision(citation_effective_date="2000-01-01"))
    rows = repo.get_decisions(claim_id="CLM-001")
    assert len(rows) == 1
    assert rows[0]["citation_effective_date"] == "2000-01-01"


def test_audit_save_with_null_effective_date(repo):
    """Audit save must accept None for citation_effective_date (optional field)."""
    repo.save_decision(_make_decision(citation_effective_date=None))
    rows = repo.get_decisions(claim_id="CLM-001")
    assert len(rows) == 1
    assert rows[0]["citation_effective_date"] is None


def test_audit_migration_adds_column_to_existing_db(tmp_path):
    """initialize_database() on a legacy DB (no effective_date column) must add the column."""
    db_path = tmp_path / "legacy.db"

    # Create a DB without the citation_effective_date column (simulating pre-Sprint 3 DB)
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE audit_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                finding_id TEXT NOT NULL,
                source TEXT NOT NULL,
                severity TEXT NOT NULL,
                issue TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                citation_source TEXT NOT NULL,
                citation_doc_id TEXT NOT NULL,
                citation_section TEXT NOT NULL,
                citation_edition TEXT NOT NULL,
                confidence REAL NOT NULL,
                user_decision TEXT NOT NULL,
                override_reason TEXT NOT NULL DEFAULT '',
                reviewer_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL
            )
        """)
        conn.commit()

    # Sprint 3 initialize_database() must add the column without error
    repo = AuditRepository(db_path=db_path)
    repo.initialize_database()  # should not raise

    # Verify the column now exists by saving a decision
    decision = _make_decision(citation_effective_date="2000-01-01")
    repo.save_decision(decision)
    rows = repo.get_decisions()
    assert len(rows) == 1
    assert rows[0]["citation_effective_date"] == "2000-01-01"


# ---------------------------------------------------------------------------
# LCD/NCD corpus retrieval coverage (Option A corpus expansion)
# ---------------------------------------------------------------------------

_LCD_NCD_SOURCE_TYPES = {"LCD", "NCD"}


def _lcd_ncd_doc_ids(results: list[dict]) -> set[str]:
    """Return document_ids of LCD and NCD entries from a retrieval result set."""
    return {p["document_id"] for p in results if p.get("source_type") in _LCD_NCD_SOURCE_TYPES}


def test_lcd_ncd_count_after_corpus_expansion():
    """After corpus expansion, there should be at least 15 LCD/NCD entries total."""
    all_policies = load_policy_references()
    lcd_ncd = [p for p in all_policies if p.get("source_type") in _LCD_NCD_SOURCE_TYPES]
    assert len(lcd_ncd) >= 15, (
        f"Expected at least 15 LCD/NCD entries after corpus expansion, found {len(lcd_ncd)}"
    )


# Required codes — each must retrieve at least one LCD/NCD entry.

def test_retrieval_z00_00_returns_lcd():
    results = find_policies_by_codes(icd10_codes=["Z00.00"])
    assert _lcd_ncd_doc_ids(results), "Z00.00 should match at least one LCD/NCD"


def test_retrieval_z00_01_returns_lcd():
    results = find_policies_by_codes(icd10_codes=["Z00.01"])
    assert _lcd_ncd_doc_ids(results), "Z00.01 should match at least one LCD/NCD"


def test_retrieval_i10_returns_lcd():
    results = find_policies_by_codes(icd10_codes=["I10"])
    assert _lcd_ncd_doc_ids(results), "I10 should match at least one LCD/NCD"


def test_retrieval_e11_9_returns_lcd():
    results = find_policies_by_codes(icd10_codes=["E11.9"])
    assert _lcd_ncd_doc_ids(results), "E11.9 should match at least one LCD/NCD"


def test_retrieval_99213_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["99213"])
    assert _lcd_ncd_doc_ids(results), "99213 should match at least one LCD/NCD"


def test_retrieval_99214_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["99214"])
    assert _lcd_ncd_doc_ids(results), "99214 should match at least one LCD/NCD"


def test_retrieval_99395_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["99395"])
    assert _lcd_ncd_doc_ids(results), "99395 should match at least one LCD/NCD"


def test_retrieval_80048_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["80048"])
    assert _lcd_ncd_doc_ids(results), "80048 should match at least one LCD/NCD"


def test_retrieval_80053_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["80053"])
    assert _lcd_ncd_doc_ids(results), "80053 should match at least one LCD/NCD"


def test_retrieval_36415_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["36415"])
    assert _lcd_ncd_doc_ids(results), "36415 should match at least one LCD/NCD"


# New codes added by corpus expansion.

def test_retrieval_e78_5_returns_lcd():
    results = find_policies_by_codes(icd10_codes=["E78.5"])
    assert _lcd_ncd_doc_ids(results), "E78.5 should match at least one LCD/NCD"


def test_retrieval_83036_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["83036"])
    assert _lcd_ncd_doc_ids(results), "83036 should match at least one LCD/NCD"


def test_retrieval_80061_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["80061"])
    assert _lcd_ncd_doc_ids(results), "80061 should match at least one LCD/NCD"


def test_retrieval_99396_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["99396"])
    assert _lcd_ncd_doc_ids(results), "99396 should match at least one LCD/NCD"


def test_retrieval_g0439_returns_ncd():
    results = find_policies_by_codes(cpt_codes=["G0439"])
    assert _lcd_ncd_doc_ids(results), "G0439 should match at least one NCD"


def test_retrieval_45378_returns_ncd():
    results = find_policies_by_codes(cpt_codes=["45378"])
    assert _lcd_ncd_doc_ids(results), "45378 should match at least one NCD"


def test_retrieval_z12_11_returns_lcd():
    results = find_policies_by_codes(icd10_codes=["Z12.11"])
    assert _lcd_ncd_doc_ids(results), "Z12.11 should match at least one LCD/NCD"


def test_retrieval_77067_returns_ncd():
    results = find_policies_by_codes(cpt_codes=["77067"])
    assert _lcd_ncd_doc_ids(results), "77067 should match at least one NCD"


def test_retrieval_m54_9_returns_lcd():
    results = find_policies_by_codes(icd10_codes=["M54.9"])
    assert _lcd_ncd_doc_ids(results), "M54.9 should match at least one LCD/NCD"


def test_retrieval_99490_returns_lcd():
    results = find_policies_by_codes(cpt_codes=["99490"])
    assert _lcd_ncd_doc_ids(results), "99490 should match at least one LCD/NCD"


# Demo scenario retrieval tests.

def test_demo_scenario_1_labs_with_well_visit_dx():
    """80053 + 83036 + Z00.00 retrieves lab necessity and HbA1c frequency policies."""
    results = find_policies_by_codes(cpt_codes=["80053", "83036"], icd10_codes=["Z00.00"])
    doc_ids = _lcd_ncd_doc_ids(results)
    assert "LCD_LAB_MEDICAL_NECESSITY_METABOLIC" in doc_ids
    assert "LCD_HEMOGLOBIN_A1C_FREQUENCY" in doc_ids


def test_demo_scenario_2_diabetes_management():
    """E11.9 + 99214 retrieves diabetes management LCD."""
    results = find_policies_by_codes(cpt_codes=["99214"], icd10_codes=["E11.9"])
    doc_ids = _lcd_ncd_doc_ids(results)
    assert "LCD_DIABETES_MGMT_E11" in doc_ids


def test_demo_scenario_3_screening_colonoscopy_with_polypectomy():
    """45385 + Z12.11 retrieves both colonoscopy policies."""
    results = find_policies_by_codes(cpt_codes=["45385"], icd10_codes=["Z12.11"])
    doc_ids = _lcd_ncd_doc_ids(results)
    assert "NCD_COLORECTAL_SCREENING_COLONOSCOPY" in doc_ids
    assert "LCD_COLONOSCOPY_DIAGNOSIS_Z12" in doc_ids


def test_demo_scenario_4_unspecified_diagnosis():
    """M54.9 + 99215 retrieves specificity and E/M level documentation policies."""
    results = find_policies_by_codes(cpt_codes=["99215"], icd10_codes=["M54.9"])
    doc_ids = _lcd_ncd_doc_ids(results)
    assert "LCD_DIAGNOSIS_SPECIFICITY_REQ" in doc_ids
    assert "LCD_EM_CODING_LEVEL_SUPPORT" in doc_ids


def test_demo_scenario_5_awv_same_day_em():
    """G0439 + 99213 + Z00.00 retrieves AWV NCD."""
    results = find_policies_by_codes(cpt_codes=["G0439", "99213"], icd10_codes=["Z00.00"])
    doc_ids = _lcd_ncd_doc_ids(results)
    assert "NCD_AWV_G0438_G0439" in doc_ids


def test_demo_scenario_6_hba1c_for_established_diabetic():
    """83036 + E11.65 retrieves HbA1c frequency and diabetes management policies."""
    results = find_policies_by_codes(cpt_codes=["83036"], icd10_codes=["E11.65"])
    doc_ids = _lcd_ncd_doc_ids(results)
    assert "LCD_HEMOGLOBIN_A1C_FREQUENCY" in doc_ids
    assert "LCD_DIABETES_MGMT_E11" in doc_ids
