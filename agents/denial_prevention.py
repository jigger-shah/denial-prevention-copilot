"""
Denial Prevention Agent — deterministic synthesis, no LLM call.

Combines rule-layer findings and coverage-agent findings into a single
RiskAssessment. This module makes no model calls and performs no retrieval —
it is pure aggregation over already-produced Finding objects, consistent with
CLAUDE.md's "orchestrator is a Python controller, not an agent loop."

Scoring reuses rules.rule_engine.overall_risk() (severity-based: HIGH > MEDIUM
> LOW > CLEAN) applied to the combined finding list, rather than inventing a
new scoring scheme — the existing rule is already well-tested and the PRD does
not ask for anything more sophisticated at this stage.

Escalation is a separate signal from severity: a finding can be HIGH-severity
and high-confidence (certain, no escalation needed beyond normal review) or
lower-confidence (the agent isn't sure — surface it for a human to triage).
CONFIDENCE_REVIEW_THRESHOLD matches the value already used for the per-finding
"Manual Review Recommended" caption in app/main.py, so claim-level escalation
and finding-level captions agree on the same number rather than drifting.

Scope note (Phase 7, light orchestrator): only rule findings and coverage
findings are combined here. Documentation Review and Coding Validation are
deferred — see docs/Roadmap.md and docs/Technical_Debt_Register.md TD-04 —
and this module does not fabricate placeholder findings for either.
"""

from __future__ import annotations

from rules.models import Finding, RiskAssessment
from rules.rule_engine import overall_risk

CONFIDENCE_REVIEW_THRESHOLD = 0.70

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def synthesize(
    rule_findings: list[Finding],
    coverage_findings: list[Finding],
    checks_run: list[str],
) -> RiskAssessment:
    """
    Combine rule and coverage findings into one RiskAssessment.

    checks_run is passed through as given by the caller (agents.orchestrator) —
    this function does not decide what ran, only how to score what came back.
    """
    all_findings = sorted(
        [*rule_findings, *coverage_findings],
        key=lambda f: _SEVERITY_ORDER.get(f.severity, len(_SEVERITY_ORDER)),
    )

    return RiskAssessment(
        score=overall_risk(all_findings),
        findings=all_findings,
        escalation_required=any(f.confidence < CONFIDENCE_REVIEW_THRESHOLD for f in all_findings),
        checks_run=checks_run,
    )
