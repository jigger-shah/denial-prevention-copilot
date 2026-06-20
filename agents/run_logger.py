"""
Lightweight structured logging for orchestrator-dispatched checks (v1.6, partial
close of TD-16 — "No Application Logging").

Scope is deliberately narrow: one JSON line per check (rule layer, coverage
agent, coding agent) per claim review, written to a local file. No external
observability platform, no metrics backend — just enough to answer "what ran,
did it succeed, how long did it take, how many findings did it produce" from a
local log file during development or a demo session.

Log line fields: timestamp, claim_id, agent, finding_count, success, latency_ms,
and error (only present on failure).
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
from contextlib import contextmanager
from datetime import datetime, timezone

LOG_DIR = pathlib.Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "agent_runs.jsonl"

_logger = logging.getLogger("denial_copilot.runs")
_logger.setLevel(logging.INFO)

if not _logger.handlers:
    LOG_DIR.mkdir(exist_ok=True)
    _handler = logging.FileHandler(LOG_FILE)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.propagate = False


def log_run(*, claim_id: str, agent: str, finding_count: int, success: bool, latency_ms: float, error: str = "") -> None:
    """Write one structured JSON line for a completed check."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "claim_id": claim_id,
        "agent": agent,
        "finding_count": finding_count,
        "success": success,
        "latency_ms": round(latency_ms, 1),
    }
    if error:
        record["error"] = error
    _logger.info(json.dumps(record))


@contextmanager
def timed_run(*, claim_id: str, agent: str):
    """
    Context manager that times a check and logs the result. Yields a mutable
    dict the caller fills with `finding_count` before the block exits.

    Usage:
        with timed_run(claim_id=claim.claim_id, agent="coverage_validation") as result:
            findings, retrieved_policies = validate_coverage(claim)
            result["finding_count"] = len(findings)
    """
    start = time.perf_counter()
    result: dict = {"finding_count": 0}
    try:
        yield result
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        log_run(claim_id=claim_id, agent=agent, finding_count=0, success=False, latency_ms=latency_ms, error=str(exc))
        raise
    else:
        latency_ms = (time.perf_counter() - start) * 1000
        log_run(
            claim_id=claim_id,
            agent=agent,
            finding_count=result.get("finding_count", 0),
            success=True,
            latency_ms=latency_ms,
        )
