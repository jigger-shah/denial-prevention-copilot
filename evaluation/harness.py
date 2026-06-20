"""
Golden-set evaluation harness.

Runs agents.orchestrator.run_review() against every claim in
evaluation/golden_claims.json, normalizes the resulting findings into the
label vocabulary defined in evaluation/metrics.py, and compares them against
each claim's expected_findings.

Two modes:

  offline (default) — agents.orchestrator.validate_coverage and
    validate_coding are patched to always return []. No Anthropic API call is
    made. The rule layer runs unmodified and for real. This is the mode used
    by tests/test_evaluation.py and by default CI/local runs. Its tradeoff:
    claims whose expected_findings include "coverage_medical_necessity" or
    "coding_defensibility" will show those as false negatives, because the
    agent that would have found them never ran. That's expected, not a bug —
    see the per-category metrics, where Coverage Agent / Coding Agent recall
    in offline mode reflects "agent did not run," not "agent missed it."

  live — real agents.coverage_validation.validate_coverage and
    agents.coding_validation.validate_coding calls are made, using whichever
    model they already default to (claude-sonnet-4-6, per CLAUDE.md — set the
    ANTHROPIC_MODEL env var to compare other models, e.g. claude-haiku-4-5 or
    claude-opus-4-8). Costs real API calls; never used by the automated test
    suite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from agents import orchestrator
from evaluation.metrics import LABEL_CATEGORY, PRF, aggregate_prf, compute_prf, normalize_findings
from rules.rule_engine import load_claim

_DEFAULT_GOLDEN_SET_PATH = Path(__file__).parent / "golden_claims.json"

CATEGORIES = ["Rule Engine", "Coverage Agent", "Coding Agent"]


@dataclass
class ClaimResult:
    claim_id: str
    description: str
    expected: set[str]
    actual: set[str]
    prf: PRF


@dataclass
class EvaluationReport:
    mode: str
    claim_results: list[ClaimResult]
    overall: PRF
    by_category: dict[str, PRF]


def load_golden_claims(path: Path = _DEFAULT_GOLDEN_SET_PATH) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _run_one_claim(claim_dict: dict) -> set[str]:
    claim = load_claim(claim_dict)
    risk_assessment = orchestrator.run_review(claim)
    return normalize_findings(risk_assessment.findings)


def run_evaluation(
    golden_claims: list[dict] | None = None,
    live: bool = False,
) -> EvaluationReport:
    """
    Evaluate the full review pipeline against a golden claim set.

    golden_claims defaults to evaluation/golden_claims.json. Set live=True to
    make real Coverage/Coding Agent API calls instead of mocking them out.
    """
    if golden_claims is None:
        golden_claims = load_golden_claims()

    if live:
        actual_by_claim = {c["claim_id"]: _run_one_claim(c) for c in golden_claims}
    else:
        with patch.object(orchestrator, "validate_coverage", return_value=[]), \
             patch.object(orchestrator, "validate_coding", return_value=[]):
            actual_by_claim = {c["claim_id"]: _run_one_claim(c) for c in golden_claims}

    claim_results: list[ClaimResult] = []
    for claim_dict in golden_claims:
        expected = set(claim_dict.get("expected_findings", []))
        actual = actual_by_claim[claim_dict["claim_id"]]
        claim_results.append(ClaimResult(
            claim_id=claim_dict["claim_id"],
            description=claim_dict.get("description", ""),
            expected=expected,
            actual=actual,
            prf=compute_prf(expected, actual),
        ))

    overall = aggregate_prf([(r.expected, r.actual) for r in claim_results])

    by_category: dict[str, PRF] = {}
    for category in CATEGORIES:
        pairs = [
            (
                {label for label in r.expected if LABEL_CATEGORY.get(label) == category},
                {label for label in r.actual if LABEL_CATEGORY.get(label) == category},
            )
            for r in claim_results
        ]
        by_category[category] = aggregate_prf(pairs)

    return EvaluationReport(
        mode="live" if live else "offline",
        claim_results=claim_results,
        overall=overall,
        by_category=by_category,
    )
