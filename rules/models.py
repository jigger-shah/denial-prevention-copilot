"""
Shared data models for the rule layer.

ClaimIn    — input contract for all rule functions.
Citation   — structured source metadata attached to every finding.
Finding    — output contract; every rule returns a list of these.

All three are plain dataclasses (no external dependencies) so they can be
imported by rule modules, the rule engine, the UI, and tests without
pulling in the full agent or DB stack.

Citation design notes
---------------------
The flat citation string used in Sprint 1 could not map cleanly to the
three-column DB schema (citation_doc_id, citation_section, citation_effective_date)
or to the source-excerpt display required by the PRD.  Citation is now a
first-class dataclass with one field per intended DB column plus an optional
excerpt for inline display.

When real CMS data files are loaded, `doc_id` becomes the versioned filename
(e.g. "NCCI-PTP-2026Q1"), `edition` becomes the quarter/year, and
`effective_date` is read from the file header.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class ClaimIn:
    claim_id: str
    payer: str
    npi: str
    cpt_codes: list
    icd10_codes: list
    modifiers: list
    place_of_service: str
    units: dict
    note_text: str = ""
    description: str = ""


@dataclass
class Citation:
    source: str                         # human label: "NCCI PTP", "ICD-10-CM", etc.
    doc_id: str                         # stable document identifier for DB storage
    section: str                        # table, chapter, or policy section cited
    edition: str                        # version consulted: quarter, FY, or "synthetic sample"
    effective_date: Optional[str] = None  # ISO-8601 date when this rule took effect
    excerpt: Optional[str] = None        # verbatim source text, shown inline in UI


@dataclass
class Finding:
    rule: str                                    # machine-readable rule identifier
    severity: Literal["HIGH", "MEDIUM", "LOW"]   # validated type; enforced by type checker
    issue: str                                   # short human-readable problem description
    recommendation: str                          # what the specialist should do
    citation: Citation                           # structured source reference
    confidence: float                            # 0.0–1.0; drives escalation in agent layer
    finding_id: str = ""                         # set by rule_engine after creation; empty until stamped
    source: str = "rule_layer"                   # "rule_layer" | "agent_layer"


@dataclass
class RiskAssessment:
    """
    Claim-level synthesis returned by agents.orchestrator.run_review().

    score is one of "HIGH" | "MEDIUM" | "LOW" | "CLEAN" — derived from the
    same severity ordering rules.rule_engine.overall_risk() already uses,
    applied across the combined rule + agent findings rather than rules alone.

    escalation_required is set when any finding's confidence falls below the
    review threshold (see agents.denial_prevention.CONFIDENCE_REVIEW_THRESHOLD) —
    a claim-level signal, distinct from the existing per-finding "Manual Review
    Recommended" caption already shown in the UI.

    checks_run lists only checks that actually executed for this claim (e.g. a
    HIGH NPI short-circuit means only the NPI check ran — NCCI/MUE/code validity
    and coverage validation are absent from this list, not just absent from findings).
    """
    score: str
    findings: list[Finding]
    escalation_required: bool
    checks_run: list[str]
