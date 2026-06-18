"""
Claim review orchestrator — light scope (Phase 7, Session "Unified Review").

Deterministic Python controller, not a free-running LLM loop:
  1. Run the rule layer synchronously (rules.rule_engine.review_claim()). A HIGH
     NPI finding short-circuits there already — NCCI/MUE/code validity never run.
  2. If the rule layer did not short-circuit, call the Coverage Validation Agent
     (agents.coverage_validation.validate_coverage()) — the only implemented LLM
     agent. If it short-circuited, the coverage agent is not called at all: an
     invalid provider identity makes a coverage call pointless and costs an
     unnecessary API call.
  3. Pass rule findings + coverage findings to agents.denial_prevention.synthesize()
     for deterministic scoring — no LLM call happens in this module or in
     denial_prevention.

checks_run reflects only checks that actually executed this run — a short-
circuited claim's checks_run has one entry (NPI), not all six.

Scope note: Coding Validation and Documentation Review are deferred (see
docs/Roadmap.md, docs/Technical_Debt_Register.md TD-04). Coding Validation is
not built as a separate LLM agent at all — it would duplicate the rule layer's
NCCI/MUE/code_validity checks. Documentation Review is a future capability
under evaluation, not an MVP requirement; this module does not call it, does
not list it in checks_run, and does not fabricate a placeholder finding for it.
A claim with no attached note is simply reviewed on code and coverage alone.
"""

from __future__ import annotations

from agents import denial_prevention
from agents.coverage_validation import validate_coverage
from rules.models import ClaimIn, Finding, RiskAssessment
from rules.rule_engine import CHECKS_RUN, review_claim

_COVERAGE_CHECK_LABEL = "Coverage validation — LLM medical necessity review (RAG-grounded, JSON fallback)"


def run_review(claim: ClaimIn) -> RiskAssessment:
    """Run the full claim review: rule layer, then coverage agent if applicable, then synthesis."""
    rule_findings = review_claim(claim)

    if _rule_layer_short_circuited(rule_findings):
        checks_run = [CHECKS_RUN[0]]
        coverage_findings: list[Finding] = []
    else:
        checks_run = [*CHECKS_RUN, _COVERAGE_CHECK_LABEL]
        coverage_findings = validate_coverage(claim)

    return denial_prevention.synthesize(rule_findings, coverage_findings, checks_run)


def _rule_layer_short_circuited(rule_findings: list[Finding]) -> bool:
    """
    True iff review_claim() returned early on an invalid-NPI HIGH finding.

    review_claim() guarantees a HIGH npi_invalid finding only ever appears in
    the short-circuit return path — in the normal path, NPI findings included
    are MEDIUM (NPPES not found) or absent. Same detection rule already used
    in app/main.py:_render_checks_summary().
    """
    return any(f.rule == "npi_invalid" and f.severity == "HIGH" for f in rule_findings)
