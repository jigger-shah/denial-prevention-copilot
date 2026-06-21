"""
Tests for AuditRepository — persistence, validation, filtering, and CSV export.

All tests use an isolated in-memory (tmp_path) SQLite database; the production
db/audit.db is never touched.
"""

import dataclasses
import pathlib
import tempfile

import pytest

from db.audit_repository import DB_PATH, AuditDecision, AuditRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    r = AuditRepository(db_path=tmp_path / "test_audit.db")
    r.initialize_database()
    return r


def _make_decision(**overrides) -> AuditDecision:
    """Return a valid accepted decision; override any fields via kwargs."""
    base = AuditDecision(
        claim_id="CLM-001",
        finding_id="abc123def456",
        source="rule_layer",
        severity="HIGH",
        issue="Bundled code pair: 80048 is a component of 80053",
        recommendation="Remove 80048 when billed with 80053.",
        citation_source="NCCI PTP",
        citation_doc_id="NCCI-PTP-SYNTHETIC",
        citation_section="Column 1 / Column 2",
        citation_edition="synthetic sample",
        confidence=0.95,
        user_decision="accepted",
        override_reason="",
        reviewer_name="Dr. Test",
        model_version="rule_layer_v0.1",
        prompt_version="n/a",
    )
    return dataclasses.replace(base, **overrides)


# ---------------------------------------------------------------------------
# Default DB path (Phase 10 — Streamlit Cloud ephemeral filesystem)
# ---------------------------------------------------------------------------

def test_default_db_path_is_under_temp_dir():
    """DB_PATH must default to the OS temp dir, not a path inside this package —
    Streamlit Cloud's filesystem is ephemeral, and a temp-dir path makes the
    audit trail's reset-on-restart behavior explicit rather than accidental."""
    assert DB_PATH.parent == pathlib.Path(tempfile.gettempdir())
    assert DB_PATH.name == "denial_copilot_audit.db"


def test_get_decisions_self_heals_when_table_missing(tmp_path):
    """If the DB file exists but audit_decisions is missing (e.g. the OS temp
    dir was cleared out from under a long-running cached AuditRepository),
    a read must not raise 'no such table' — the schema must be (re)applied
    transparently and the call must succeed with an empty result."""
    import sqlite3

    db_path = tmp_path / "schemaless.db"
    sqlite3.connect(db_path).close()  # file exists, no tables

    repo = AuditRepository(db_path=db_path)
    assert repo.get_decisions() == []


def test_export_decisions_csv_self_heals_when_table_missing(tmp_path):
    """Same self-healing guarantee for the CSV export read path."""
    import sqlite3

    db_path = tmp_path / "schemaless_export.db"
    sqlite3.connect(db_path).close()

    repo = AuditRepository(db_path=db_path)
    assert repo.export_decisions_csv() == ""


def test_save_decision_self_heals_when_table_missing(tmp_path):
    """A save against a DB file with no schema must create the schema and
    succeed, rather than requiring a prior explicit initialize_database()."""
    import sqlite3

    db_path = tmp_path / "schemaless_save.db"
    sqlite3.connect(db_path).close()

    repo = AuditRepository(db_path=db_path)
    repo.save_decision(_make_decision())
    rows = repo.get_decisions()
    assert len(rows) == 1
    assert rows[0]["finding_id"] == "abc123def456"


def test_repository_with_no_db_path_arg_uses_default():
    """AuditRepository() with no args must still work end-to-end against the
    temp-dir default — explicit db_path (as every other test uses) must remain
    a fully-supported override, not the only working path."""
    DB_PATH.unlink(missing_ok=True)
    try:
        repo = AuditRepository()
        assert repo._db_path == DB_PATH
        repo.initialize_database()
        decision = _make_decision()
        repo.save_decision(decision)
        rows = repo.get_decisions(claim_id=decision.claim_id)
        assert any(r["finding_id"] == decision.finding_id for r in rows)
    finally:
        DB_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_accepted_decision_persists(repo):
    """A saved accepted decision must be retrievable with the correct fields."""
    repo.save_decision(_make_decision(user_decision="accepted"))

    rows = repo.get_decisions(claim_id="CLM-001")
    assert len(rows) == 1
    row = rows[0]
    assert row["user_decision"] == "accepted"
    assert row["finding_id"] == "abc123def456"
    assert row["reviewer_name"] == "Dr. Test"
    assert row["claim_id"] == "CLM-001"
    assert row["timestamp"]  # non-empty ISO timestamp


def test_overridden_decision_persists_with_reason(repo):
    """An override decision with a reason must persist both the decision and the reason."""
    repo.save_decision(_make_decision(
        user_decision="overridden",
        override_reason="Provider confirmed separate diagnosis in chart",
    ))

    rows = repo.get_decisions()
    assert rows[0]["user_decision"] == "overridden"
    assert rows[0]["override_reason"] == "Provider confirmed separate diagnosis in chart"


def test_citation_excerpt_persists(repo):
    """TD-20: citation_excerpt must round-trip through save_decision/get_decisions."""
    repo.save_decision(_make_decision(
        citation_excerpt="CPT code 80048 is a component of CPT code 80053.",
    ))

    rows = repo.get_decisions(claim_id="CLM-001")
    assert rows[0]["citation_excerpt"] == "CPT code 80048 is a component of CPT code 80053."


def test_citation_excerpt_defaults_to_none(repo):
    """Decisions saved without an explicit excerpt must not fail and store NULL."""
    repo.save_decision(_make_decision())

    rows = repo.get_decisions(claim_id="CLM-001")
    assert rows[0]["citation_excerpt"] is None


def test_initialize_database_is_idempotent_with_excerpt_migration(tmp_path):
    """Calling initialize_database() twice (simulating an existing pre-v1.7 DB) must not raise."""
    db_path = tmp_path / "preexisting.db"
    r1 = AuditRepository(db_path=db_path)
    r1.initialize_database()
    r2 = AuditRepository(db_path=db_path)
    r2.initialize_database()  # should not raise even though the column already exists

    r2.save_decision(_make_decision(citation_excerpt="re-init still works"))
    rows = r2.get_decisions()
    assert rows[0]["citation_excerpt"] == "re-init still works"


def test_multiple_decisions_accumulate(repo):
    """The table is append-only; multiple saves must all be present."""
    repo.save_decision(_make_decision(finding_id="id_aaa"))
    repo.save_decision(_make_decision(finding_id="id_bbb"))
    repo.save_decision(_make_decision(finding_id="id_ccc"))

    assert len(repo.get_decisions()) == 3


# ---------------------------------------------------------------------------
# Validation — override requires reason
# ---------------------------------------------------------------------------

def test_override_requires_reason(repo):
    """save_decision must raise ValueError when override_reason is empty."""
    with pytest.raises(ValueError, match="override_reason"):
        repo.save_decision(_make_decision(user_decision="overridden", override_reason=""))


def test_override_whitespace_reason_rejected(repo):
    """Whitespace-only override reason must also be rejected."""
    with pytest.raises(ValueError, match="override_reason"):
        repo.save_decision(_make_decision(user_decision="overridden", override_reason="   "))


# ---------------------------------------------------------------------------
# Validation — citation required
# ---------------------------------------------------------------------------

def test_finding_without_citation_source_rejected(repo):
    """save_decision must raise ValueError when citation_source is empty."""
    with pytest.raises(ValueError, match="citation"):
        repo.save_decision(_make_decision(citation_source=""))


def test_finding_without_citation_doc_id_rejected(repo):
    """save_decision must raise ValueError when citation_doc_id is empty."""
    with pytest.raises(ValueError, match="citation"):
        repo.save_decision(_make_decision(citation_doc_id=""))


def test_finding_without_finding_id_rejected(repo):
    """save_decision must raise ValueError when finding_id is empty."""
    with pytest.raises(ValueError, match="finding_id"):
        repo.save_decision(_make_decision(finding_id=""))


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def test_filter_by_claim_id(repo):
    """get_decisions(claim_id=...) must return only rows for that claim."""
    repo.save_decision(_make_decision(claim_id="CLM-001"))
    repo.save_decision(_make_decision(claim_id="CLM-002", finding_id="xyz"))

    rows = repo.get_decisions(claim_id="CLM-001")
    assert len(rows) == 1
    assert rows[0]["claim_id"] == "CLM-001"


def test_filter_by_reviewer_name(repo):
    """get_decisions(reviewer_name=...) must return only rows for that reviewer."""
    repo.save_decision(_make_decision(reviewer_name="Alice"))
    repo.save_decision(_make_decision(reviewer_name="Bob", finding_id="xyz"))

    rows = repo.get_decisions(reviewer_name="Alice")
    assert len(rows) == 1
    assert rows[0]["reviewer_name"] == "Alice"


def test_no_filter_returns_all(repo):
    """get_decisions() with no filters must return all rows."""
    repo.save_decision(_make_decision(claim_id="CLM-001", finding_id="id1"))
    repo.save_decision(_make_decision(claim_id="CLM-002", finding_id="id2"))

    assert len(repo.get_decisions()) == 2


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def test_export_contains_expected_columns(repo):
    """The CSV header must include all audit-trail columns."""
    repo.save_decision(_make_decision())
    csv_str = repo.export_decisions_csv()

    header = csv_str.split("\n")[0]
    expected_cols = [
        "id", "timestamp", "claim_id", "finding_id", "severity",
        "user_decision", "reviewer_name", "confidence",
        "citation_source", "citation_doc_id", "citation_excerpt",
    ]
    for col in expected_cols:
        assert col in header, f"Expected column '{col}' missing from CSV header"


def test_export_empty_when_no_decisions(repo):
    """export_decisions_csv must return an empty string when there are no rows."""
    assert repo.export_decisions_csv() == ""


def test_export_filter_by_claim_id(repo):
    """export_decisions_csv must respect the claim_id filter."""
    repo.save_decision(_make_decision(claim_id="CLM-001"))
    repo.save_decision(_make_decision(claim_id="CLM-002", finding_id="xyz"))

    csv_str = repo.export_decisions_csv(claim_id="CLM-001")
    lines = [l for l in csv_str.strip().split("\n") if l]
    # 1 header + 1 data row
    assert len(lines) == 2
    assert "CLM-001" in csv_str
    assert "CLM-002" not in csv_str


def test_export_row_count_matches_get_decisions(repo):
    """Row count in CSV must equal len(get_decisions()) for the same filters."""
    repo.save_decision(_make_decision(finding_id="id1"))
    repo.save_decision(_make_decision(finding_id="id2"))

    csv_str = repo.export_decisions_csv()
    data_rows = [l for l in csv_str.strip().split("\n") if l][1:]  # skip header
    assert len(data_rows) == len(repo.get_decisions())
