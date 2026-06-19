"""
CLI entry point for the golden-set evaluation harness.

Usage:
    python -m evaluation.run_evaluation            # offline, mocked agents (default, no API calls)
    python -m evaluation.run_evaluation --live      # real Coverage/Coding Agent API calls

Saves three files into evaluation/:
    latest_report.md     human-readable metrics table + per-claim results
    latest_results.json  claim-level expected/actual labels + per-claim PRF
    latest_summary.json  overall + per-category metrics only
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from evaluation.harness import EvaluationReport, run_evaluation

_OUTPUT_DIR = Path(__file__).parent


def _prf_row(label: str, prf) -> str:
    return (
        f"| {label} | {prf.true_positives} | {prf.false_positives} | {prf.false_negatives} "
        f"| {prf.precision:.2f} | {prf.recall:.2f} | {prf.f1:.2f} |"
    )


def render_markdown_report(report: EvaluationReport) -> str:
    lines = [
        "# Golden Set Evaluation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Mode: **{report.mode}**"
        + (
            "" if report.mode == "live"
            else " — Coverage/Coding Agent calls mocked to return no findings; "
                 "their categories below reflect that, not agent accuracy. Run with --live for a real read."
        ),
        f"Claims evaluated: {len(report.claim_results)}",
        "",
        "## Metrics",
        "",
        "| Category | TP | FP | FN | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|",
        _prf_row("Overall", report.overall),
    ]
    for category, prf in report.by_category.items():
        lines.append(_prf_row(category, prf))

    lines += ["", "## Claim-level results", "", "| Claim | Expected | Actual | TP | FP | FN |", "|---|---|---|---|---|---|"]
    for r in report.claim_results:
        expected = ", ".join(sorted(r.expected)) or "(none)"
        actual = ", ".join(sorted(r.actual)) or "(none)"
        lines.append(f"| {r.claim_id} | {expected} | {actual} | {r.prf.true_positives} | {r.prf.false_positives} | {r.prf.false_negatives} |")

    return "\n".join(lines) + "\n"


def report_to_results_json(report: EvaluationReport) -> list[dict]:
    return [
        {
            "claim_id": r.claim_id,
            "description": r.description,
            "expected_findings": sorted(r.expected),
            "actual_findings": sorted(r.actual),
            "true_positives": r.prf.true_positives,
            "false_positives": r.prf.false_positives,
            "false_negatives": r.prf.false_negatives,
            "precision": r.prf.precision,
            "recall": r.prf.recall,
            "f1": r.prf.f1,
        }
        for r in report.claim_results
    ]


def report_to_summary_json(report: EvaluationReport) -> dict:
    return {
        "mode": report.mode,
        "claims_evaluated": len(report.claim_results),
        "overall": asdict(report.overall),
        "by_category": {category: asdict(prf) for category, prf in report.by_category.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the golden-set evaluation.")
    parser.add_argument(
        "--live", action="store_true",
        help="Make real Coverage/Coding Agent API calls instead of mocking them out.",
    )
    args = parser.parse_args()

    report = run_evaluation(live=args.live)

    (_OUTPUT_DIR / "latest_report.md").write_text(render_markdown_report(report))
    (_OUTPUT_DIR / "latest_results.json").write_text(json.dumps(report_to_results_json(report), indent=2))
    (_OUTPUT_DIR / "latest_summary.json").write_text(json.dumps(report_to_summary_json(report), indent=2))

    print(render_markdown_report(report))
    print(f"Saved: {_OUTPUT_DIR / 'latest_report.md'}, latest_results.json, latest_summary.json")


if __name__ == "__main__":
    main()
