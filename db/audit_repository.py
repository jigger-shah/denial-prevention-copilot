"""
Audit repository — SQLite persistence for human review decisions.

All writes go through AuditRepository; the UI must never call sqlite3 directly.
The audit_decisions table is append-only: no UPDATE, no DELETE.

Usage:
    repo = AuditRepository()          # defaults to a temp-dir audit.db
    repo.initialize_database()
    repo.save_decision(decision)
    rows = repo.get_decisions(claim_id="CLM-001")
    csv_str = repo.export_decisions_csv()

DB_PATH defaults to the OS temp directory rather than a path inside this
package. Streamlit Cloud's filesystem is ephemeral — the audit trail is not
expected to survive an app restart/redeploy there, and a temp-dir path makes
that explicit rather than accidental (see README's "AI features" section).
Within a single running session the database still works exactly as before;
pass db_path explicitly (as the tests do) to use a different location.
"""

import csv
import io
import pathlib
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

DB_PATH = pathlib.Path(tempfile.gettempdir()) / "denial_copilot_audit.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_decisions (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                TEXT    NOT NULL,
    claim_id                 TEXT    NOT NULL,
    finding_id               TEXT    NOT NULL,
    source                   TEXT    NOT NULL,
    severity                 TEXT    NOT NULL,
    issue                    TEXT    NOT NULL,
    recommendation           TEXT    NOT NULL,
    citation_source          TEXT    NOT NULL,
    citation_doc_id          TEXT    NOT NULL,
    citation_section         TEXT    NOT NULL,
    citation_edition         TEXT    NOT NULL,
    citation_effective_date  TEXT,
    citation_excerpt         TEXT,
    confidence               REAL    NOT NULL,
    user_decision            TEXT    NOT NULL,
    override_reason          TEXT    NOT NULL DEFAULT '',
    reviewer_name            TEXT    NOT NULL,
    model_version            TEXT    NOT NULL,
    prompt_version           TEXT    NOT NULL
);
"""

# Backward-compatible migration: add citation_effective_date to existing databases
# that were created before Sprint 3. ALTER TABLE ADD COLUMN in SQLite is safe —
# it never destroys existing rows and defaults the new column to NULL.
_MIGRATE_ADD_EFFECTIVE_DATE_SQL = """
ALTER TABLE audit_decisions ADD COLUMN citation_effective_date TEXT;
"""

# Backward-compatible migration: add citation_excerpt to existing databases
# that were created before v1.7 (TD-20). Same safe ALTER TABLE pattern as above.
_MIGRATE_ADD_EXCERPT_SQL = """
ALTER TABLE audit_decisions ADD COLUMN citation_excerpt TEXT;
"""

_INSERT_SQL = """
INSERT INTO audit_decisions (
    timestamp, claim_id, finding_id, source, severity, issue,
    recommendation, citation_source, citation_doc_id, citation_section,
    citation_edition, citation_effective_date, citation_excerpt, confidence,
    user_decision, override_reason, reviewer_name, model_version, prompt_version
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


@dataclass
class AuditDecision:
    """One row in audit_decisions. id and timestamp are set by the database."""
    claim_id: str
    finding_id: str
    source: str
    severity: str
    issue: str
    recommendation: str
    citation_source: str
    citation_doc_id: str
    citation_section: str
    citation_edition: str
    confidence: float
    user_decision: str       # "accepted" | "overridden"
    override_reason: str     # required (non-empty) when user_decision == "overridden"
    reviewer_name: str
    model_version: str
    prompt_version: str
    citation_effective_date: Optional[str] = None
    citation_excerpt: Optional[str] = None
    id: Optional[int] = None
    timestamp: Optional[str] = None


class AuditRepository:
    def __init__(self, db_path: pathlib.Path = DB_PATH):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        # The schema is (re)applied on every connect, not just once at startup.
        # get_repo() in app/main.py is @st.cache_resource, so initialize_database()
        # normally only runs once per server process. The default DB_PATH lives in
        # the OS temp directory, which can be cleared by the OS (or a reboot) while
        # the Streamlit process keeps running — the next sqlite3.connect() silently
        # recreates an empty file with no tables. Re-applying the idempotent
        # CREATE TABLE IF NOT EXISTS / ALTER TABLE here heals that case automatically.
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute(_CREATE_TABLE_SQL)
        try:
            conn.execute(_MIGRATE_ADD_EFFECTIVE_DATE_SQL)
        except Exception:
            pass
        try:
            conn.execute(_MIGRATE_ADD_EXCERPT_SQL)
        except Exception:
            pass
        conn.commit()
        return conn

    def initialize_database(self) -> None:
        """Create the audit_decisions table if it does not exist, and apply migrations."""
        self._connect().close()

    def save_decision(self, decision: AuditDecision) -> int:
        """
        INSERT a decision row. Returns the new row id.

        Raises ValueError if:
          - finding_id is empty (finding not stamped by rule engine)
          - citation_source or citation_doc_id is empty (no traceable citation)
          - user_decision is "overridden" and override_reason is empty
        """
        if not decision.finding_id:
            raise ValueError("Cannot save decision: finding_id is empty")
        if not decision.citation_source or not decision.citation_doc_id:
            raise ValueError("Cannot save decision: citation is incomplete (citation_source and citation_doc_id required)")
        if decision.user_decision == "overridden" and not decision.override_reason.strip():
            raise ValueError("Cannot save decision: override_reason is required when user_decision is 'overridden'")

        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                _INSERT_SQL,
                (
                    timestamp,
                    decision.claim_id,
                    decision.finding_id,
                    decision.source,
                    decision.severity,
                    decision.issue,
                    decision.recommendation,
                    decision.citation_source,
                    decision.citation_doc_id,
                    decision.citation_section,
                    decision.citation_edition,
                    decision.citation_effective_date,
                    decision.citation_excerpt,
                    decision.confidence,
                    decision.user_decision,
                    decision.override_reason,
                    decision.reviewer_name,
                    decision.model_version,
                    decision.prompt_version,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_decisions(
        self,
        claim_id: Optional[str] = None,
        reviewer_name: Optional[str] = None,
    ) -> list[dict]:
        """Return rows matching optional filters, newest first."""
        query = "SELECT * FROM audit_decisions WHERE 1=1"
        params: list = []
        if claim_id:
            query += " AND claim_id = ?"
            params.append(claim_id)
        if reviewer_name:
            query += " AND reviewer_name = ?"
            params.append(reviewer_name)
        query += " ORDER BY timestamp DESC"

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def export_decisions_csv(
        self,
        claim_id: Optional[str] = None,
        reviewer_name: Optional[str] = None,
    ) -> str:
        """Return all matching decisions as a CSV string (header + rows)."""
        rows = self.get_decisions(claim_id=claim_id, reviewer_name=reviewer_name)
        if not rows:
            return ""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
