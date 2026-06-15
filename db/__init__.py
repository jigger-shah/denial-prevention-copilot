"""
SQLite persistence layer.

Two concerns:
  schema.py — DDL and Pydantic models for claims, findings, and decisions.
  audit.py  — write and query functions for the immutable per-claim audit log.

SQLite is intentional for the MVP: zero-config, portable, exportable to CSV,
and sufficient for the demo volume. The schema is designed so the audit log table
is append-only (no UPDATE or DELETE) to preserve decision integrity.
"""
