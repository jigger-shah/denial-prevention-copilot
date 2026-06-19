"""
Tests for agents/run_logger.py — lightweight structured logging (v1.6, partial
close of TD-16). Local JSON-lines file only, no external infra.
"""

from __future__ import annotations

import json

import pytest

from agents.run_logger import log_run, timed_run


@pytest.fixture
def captured_lines(monkeypatch):
    lines: list[str] = []

    import agents.run_logger as run_logger_module

    monkeypatch.setattr(run_logger_module._logger, "info", lambda msg: lines.append(msg))
    return lines


def test_log_run_writes_required_fields(captured_lines):
    log_run(claim_id="CLM-001", agent="coverage_validation", finding_count=2, success=True, latency_ms=123.456)

    record = json.loads(captured_lines[0])
    assert record["claim_id"] == "CLM-001"
    assert record["agent"] == "coverage_validation"
    assert record["finding_count"] == 2
    assert record["success"] is True
    assert record["latency_ms"] == 123.5
    assert "timestamp" in record
    assert "error" not in record


def test_log_run_includes_error_field_on_failure(captured_lines):
    log_run(claim_id="CLM-002", agent="coding_validation", finding_count=0, success=False, latency_ms=5.0, error="boom")

    record = json.loads(captured_lines[0])
    assert record["success"] is False
    assert record["error"] == "boom"


def test_timed_run_logs_success_with_finding_count(captured_lines):
    with timed_run(claim_id="CLM-003", agent="rule_layer") as result:
        result["finding_count"] = 3

    record = json.loads(captured_lines[0])
    assert record["claim_id"] == "CLM-003"
    assert record["agent"] == "rule_layer"
    assert record["finding_count"] == 3
    assert record["success"] is True
    assert record["latency_ms"] >= 0


def test_timed_run_logs_failure_and_reraises(captured_lines):
    with pytest.raises(ValueError):
        with timed_run(claim_id="CLM-004", agent="coverage_validation"):
            raise ValueError("retrieval failed")

    record = json.loads(captured_lines[0])
    assert record["success"] is False
    assert record["finding_count"] == 0
    assert record["error"] == "retrieval failed"
