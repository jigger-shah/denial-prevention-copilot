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
