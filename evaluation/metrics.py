"""
Label normalization and precision/recall/F1 computation for the golden-set
evaluation harness.

Normalization maps a Finding's rule field (and source, for the two LLM
agents) to the simple label vocabulary used in evaluation/golden_claims.json.
This is the single place that vocabulary is defined — golden claims and the
harness both go through it, so they cannot silently drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from rules.models import Finding

# Rule-layer Finding.rule -> normalized label.
# npi_registry ("not found"/"inactive") is deliberately excluded: it can only
# fire after a live NPPES network call, which the offline-safe golden set
# avoids entirely (see CLAUDE.md "rule layer before LLM" + npi.py docstring).
RULE_LABELS: dict[str, str] = {
    "npi_invalid": "invalid_npi",
    "ncci_ptp": "ncci_conflict",
    "mue_unit_limit": "mue_limit",
    "dx_procedure_conflict": "diagnosis_procedure_mismatch",
    "missing_modifier_25": "missing_modifier_25",
}

# Agent-layer Finding.rule -> normalized label.
AGENT_LABELS: dict[str, str] = {
    "coverage_validation": "coverage_medical_necessity",
    "coding_validation": "coding_defensibility",
}

ALL_LABELS: dict[str, str] = {**RULE_LABELS, **AGENT_LABELS}

# Normalized label -> category, for per-category metric reporting.
LABEL_CATEGORY: dict[str, str] = {
    **{label: "Rule Engine" for label in RULE_LABELS.values()},
    "coverage_medical_necessity": "Coverage Agent",
    "coding_defensibility": "Coding Agent",
}


def normalize_finding(finding: Finding) -> str | None:
    """Map a single Finding to its normalized label, or None if unrecognized."""
    return ALL_LABELS.get(finding.rule)


def normalize_findings(findings: list[Finding]) -> set[str]:
    """Map a list of Findings to the set of normalized labels they produce."""
    labels = {normalize_finding(f) for f in findings}
    labels.discard(None)
    return labels


@dataclass
class PRF:
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float


def _safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def compute_prf(expected: set[str], actual: set[str]) -> PRF:
    """
    Compute true/false positive/negative counts and precision/recall/F1 for
    one comparison of expected vs. actual normalized label sets.

    A claim with no expected findings and no actual findings is a perfect
    match (precision = recall = f1 = 1.0, all counts 0), not a 0/0 -> 0.0
    case — there is nothing to miss and nothing wrongly flagged.
    """
    true_positives = len(expected & actual)
    false_positives = len(actual - expected)
    false_negatives = len(expected - actual)

    if not expected and not actual:
        return PRF(0, 0, 0, 1.0, 1.0, 1.0)

    precision = _safe_div(true_positives, true_positives + false_positives)
    recall = _safe_div(true_positives, true_positives + false_negatives)
    f1 = _safe_div(2 * precision * recall, precision + recall) if (precision + recall) else 0.0

    return PRF(true_positives, false_positives, false_negatives, precision, recall, f1)


def aggregate_prf(pairs: list[tuple[set[str], set[str]]]) -> PRF:
    """
    Micro-average precision/recall/F1 across multiple (expected, actual) pairs
    by summing raw TP/FP/FN counts first, then computing rates once.

    Micro- rather than macro-averaging is used because claim-level label sets
    are small (often 0-2 labels), so per-claim averaging would let a single
    one-label claim swing the aggregate as much as a six-label claim.
    """
    true_positives = false_positives = false_negatives = 0
    for expected, actual in pairs:
        prf = compute_prf(expected, actual)
        true_positives += prf.true_positives
        false_positives += prf.false_positives
        false_negatives += prf.false_negatives

    precision = _safe_div(true_positives, true_positives + false_positives)
    recall = _safe_div(true_positives, true_positives + false_negatives)
    f1 = _safe_div(2 * precision * recall, precision + recall) if (precision + recall) else 0.0

    return PRF(true_positives, false_positives, false_negatives, precision, recall, f1)
