"""
Streamlit entry point for the Denial Prevention Copilot.

Responsibilities:
  - Two claim entry modes: Sample Claim (synthetic JSON) and Manual Claim Entry.
  - Manual mode: claim header + service-line coding grid → build_manual_claim() → rule engine.
  - Sample mode: existing dropdown selection → rule engine (unchanged).
  - Render findings with color-coded severity badges.
  - Capture per-finding Accept / Override decisions in session state.
  - Persist decisions to SQLite via AuditRepository (never calls sqlite3 directly).
  - Audit Trail tab: view saved decisions, filter, export CSV.

All rule evaluation lives in rules/rule_engine.py.
All DB access goes through db/audit_repository.py.
Manual claim transformation lives in app/claim_intake.py (no Streamlit there).
"""

import json
import logging
import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from rules.models import Citation, Finding
from rules.rule_engine import load_claim, review_claim, overall_risk, CHECKS_RUN
from rules.data_source_status import get_data_source_status
from rules import cms_asset_fetch, icd10_loader, mue_loader, ncci_loader
from agents.coverage_validation import validate_coverage
from agents.orchestrator import run_review
from agents.secrets import get_secret
from db.audit_repository import AuditDecision, AuditRepository
from retrieval.policy_repository import get_citation_detail
from app.claim_intake import (
    PAYER_ID_MAP,
    WORKED_EXAMPLE,
    get_payer_id,
    validate_npi,
    normalize_code,
    build_manual_claim,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AI_ENABLED: bool = bool(get_secret("ANTHROPIC_API_KEY"))

CLAIMS_FILE = pathlib.Path(__file__).parent.parent / "data" / "synthetic" / "sample_claims.json"
CACHED_AI_DEMO_FILE = pathlib.Path(__file__).parent.parent / "data" / "synthetic" / "cached_ai_demo_artifacts.json"
MODEL_VERSION = "rule_layer_v0.1"
PROMPT_VERSION = "n/a"
CONFIDENCE_REVIEW_THRESHOLD = 0.70

_PAYER_PLACEHOLDER = "— Select Payer —"

_SEVERITY_STYLE = {
    "HIGH":   {"badge_bg": "#dc2626", "border": "#dc2626", "card_bg": "#fef2f2"},
    "MEDIUM": {"badge_bg": "#d97706", "border": "#d97706", "card_bg": "#fffbeb"},
    "LOW":    {"badge_bg": "#2563eb", "border": "#2563eb", "card_bg": "#eff6ff"},
}

_RISK_CONFIG = {
    "HIGH":  ("🔴 HIGH RISK — immediate attention required", "error"),
    "MEDIUM":("🟡 MEDIUM RISK — review recommended", "warning"),
    "LOW":   ("🔵 LOW RISK — minor issues noted", "info"),
    "CLEAN": ("🟢 CLEAN — no denial risks identified", "success"),
}

_SL_COLS = [1.7, 0.8, 0.8, 0.6, 1.1, 1.1, 1.1, 1.1, 0.5]
_SL_HEADERS = ["CPT / HCPCS", "Mod 1", "Mod 2", "Units", "ICD-10 (1)", "ICD-10 (2)", "ICD-10 (3)", "ICD-10 (4)", ""]

# Source label shown on each finding card — derived from the existing Finding.rule
# value, no schema change. Anything not in this map is rule-layer deterministic.
_AGENT_RULE_LABELS = {
    "coverage_validation": "Coverage Agent",
    "coding_validation": "Coding Agent",
}

# Short, plain-English "why this matters" line per rule — purely a UI lookup over
# the existing Finding.rule field, not a data-model change.
_WHY_IT_MATTERS = {
    "ncci_ptp": "This service combination may be denied because one service is bundled into another.",
    "mue_unit_limit": "Billed units exceed common Medicare unit limits for this code.",
    "missing_modifier_25": "This E/M service may need separate-identifiable-service support.",
    "missing_modifier_76": "A repeated procedure without a repeat-procedure modifier may be denied as a duplicate.",
    "missing_modifier_50": "A bilateral-eligible procedure without a bilateral modifier may be denied or down-coded.",
    "dx_procedure_conflict": "The diagnosis billed may not support a problem-oriented visit, which can trigger a denial.",
    "npi_invalid": "An invalid NPI can cause the claim to be rejected before any other check runs.",
    "npi_registry": "An NPI that can't be verified against the NPPES registry may delay or block claim processing.",
    "icd10_invalid": "Invalid diagnosis codes may cause outright claim rejection.",
    "icd10_unspecified": "Unspecified diagnosis codes may trigger additional payer scrutiny or denial.",
    "coverage_validation": "Medical necessity support for this service may be missing from the cited policy.",
    "coding_validation": "The diagnosis/coding rationale may not support the service billed.",
}

_RECOMMENDED_ACTION = {
    "HIGH": "Review before submission.",
    "MEDIUM": "Review recommended before submission.",
    "LOW": "Low risk — spot-check if time allows.",
    "CLEAN": "No action needed.",
}


# ---------------------------------------------------------------------------
# Cached resources
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_claims() -> list[dict]:
    with open(CLAIMS_FILE) as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def load_cached_ai_demo_artifacts() -> dict:
    """
    Pre-generated AI agent findings (data/synthetic/cached_ai_demo_artifacts.json),
    captured from real validate_coverage()/validate_coding() runs. Shown only when
    ANTHROPIC_API_KEY is absent, so public users can preview representative AI
    output for the designated sample claims without making a live API call.
    """
    with open(CACHED_AI_DEMO_FILE) as f:
        return json.load(f)


def _cached_ai_findings_for(claim_id: str) -> list[Finding] | None:
    artifacts = load_cached_ai_demo_artifacts()
    entry = artifacts.get(claim_id)
    if not entry:
        return None
    findings = []
    for raw in entry["findings"]:
        citation = Citation(**raw["citation"])
        findings.append(
            Finding(
                rule=raw["rule"],
                severity=raw["severity"],
                issue=raw["issue"],
                recommendation=raw["recommendation"],
                citation=citation,
                confidence=raw["confidence"],
                source=raw["source"],
            )
        )
    return findings


@st.cache_resource(show_spinner=False)
def get_repo() -> AuditRepository:
    repo = AuditRepository()
    repo.initialize_database()
    return repo


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _severity_badge(severity: str) -> str:
    style = _SEVERITY_STYLE.get(severity, {"badge_bg": "#6b7280"})
    return (
        f'<span style="background:{style["badge_bg"]};color:#fff;'
        f'padding:2px 10px;border-radius:4px;font-size:0.72rem;'
        f'font-weight:700;letter-spacing:0.05em;">{severity}</span>'
    )


def _source_label(finding) -> str:
    """Rule Engine / Coverage Agent / Coding Agent — derived from Finding.rule."""
    return _AGENT_RULE_LABELS.get(finding.rule, "Rule Engine")


def _why_it_matters(finding) -> str | None:
    return _WHY_IT_MATTERS.get(finding.rule)


def _source_badge(finding) -> str:
    label = _source_label(finding)
    bg = "#7c3aed" if label != "Rule Engine" else "#4b5563"
    return (
        f'<span style="background:{bg};color:#fff;padding:1px 8px;'
        f'border-radius:4px;font-size:0.68rem;font-weight:600;'
        f'margin-left:6px;">{label}</span>'
    )


@st.cache_resource(show_spinner=False)
def _data_source_summary() -> dict:
    """Wraps rules.data_source_status.get_data_source_status() with a
    process-lifetime cache. The underlying loaders parse the full CMS
    reference files when present locally (can take a while), and that
    parsed state doesn't change for the life of the running server —
    a short TTL would force the same slow re-parse every refresh."""
    status = get_data_source_status()
    statuses = {v["status"] for v in status.values()}
    if statuses == {"file_backed"}:
        overall = "file_backed"
    elif statuses == {"synthetic_fallback"}:
        overall = "synthetic_fallback"
    else:
        overall = "mixed"
    return {"overall": overall, "datasets": status}


def _severity_counts(findings: list) -> dict[str, int]:
    """HIGH/MEDIUM/LOW counts for the risk banner's severity summary — same
    counting logic as before, just no longer rendered as prose bullets."""
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        if f.severity in counts:
            counts[f.severity] += 1
    return counts


def _render_risk_explanation(risk_score: str, findings: list) -> None:
    """Compact High/Medium/Low severity summary + promoted Recommended Action
    callout, shown directly under the risk banner. Presentation only — the
    underlying severity counts and recommendation text are unchanged."""
    counts = _severity_counts(findings)
    col_high, col_medium, col_low = st.columns(3)
    col_high.metric("High", counts["HIGH"])
    col_medium.metric("Medium", counts["MEDIUM"])
    col_low.metric("Low", counts["LOW"])

    st.info(
        f"🛠 **Recommended Action**\n\n"
        f"{_RECOMMENDED_ACTION.get(risk_score, 'Review findings below.')}"
    )


def _citation_is_json_fallback(citation, retrieved_policies: list[dict] | None) -> bool:
    """
    True iff the policy this citation was drawn from came from the curated
    JSON fallback corpus rather than the ChromaDB vector store — so the UI
    can label the context as fallback instead of implying a live, semantically
    matched policy retrieval. Never claims live retrieval where there was none.
    """
    if not retrieved_policies:
        return False
    matching = next((p for p in retrieved_policies if p.get("document_id") == citation.doc_id), None)
    return bool(matching) and matching.get("retrieval_source") == "json_fallback"


def _citation_caption(citation) -> str:
    text = f"{citation.source} — {citation.section}"
    if citation.edition:
        text += f" ({citation.edition})"
    if citation.effective_date:
        text += f" · effective {citation.effective_date}"
    return text


def _render_citation_detail(citation) -> None:
    policy = get_citation_detail(citation)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"**Source:** {citation.source}")
        st.markdown(f"**Document ID:** `{citation.doc_id}`")
        st.markdown(f"**Section:** {citation.section}")
    with col_b:
        st.markdown(f"**Edition:** {citation.edition}")
        if citation.effective_date:
            st.markdown(f"**Effective date:** {citation.effective_date}")

    if policy:
        st.markdown(f"**Title:** {policy['title']}")
        if policy.get("source_url"):
            st.markdown(f"**Reference:** [{policy['source_url']}]({policy['source_url']})")

    if citation.excerpt:
        st.markdown("**Policy excerpt:**")
        st.markdown(
            f'<div style="font-size:0.85rem;color:#374151;font-style:italic;'
            f'padding:6px 10px;background:#f9fafb;border-left:3px solid #d1d5db;'
            f'border-radius:0 4px 4px 0;margin-top:4px;">'
            f'"{citation.excerpt}"</div>',
            unsafe_allow_html=True,
        )

    if policy and policy.get("notes"):
        st.caption(f"Notes: {policy['notes']}")


def _render_supporting_policies(retrieved_policies: list[dict], cited_doc_id: str) -> None:
    """
    TD-22: list other LCD/NCD policies the agent retrieved and considered for
    this claim but did not cite as the basis for the finding — separate from
    the primary citation so it never reads as additional evidence.
    """
    others = [p for p in retrieved_policies if p.get("document_id") != cited_doc_id]
    if not others:
        return
    with st.expander(f"📚 Supporting Policies Reviewed ({len(others)})"):
        st.caption("Considered during AI analysis but not the basis for this finding.")
        for policy in others:
            st.markdown(f"**{policy.get('title') or policy.get('document_id', '')}**")
            meta = policy.get("section", "")
            if policy.get("effective_date"):
                meta += f" · effective {policy['effective_date']}"
            if meta:
                st.caption(meta)
            excerpt = policy.get("excerpt")
            if excerpt:
                st.markdown(
                    f'<div style="font-size:0.85rem;color:#374151;font-style:italic;'
                    f'padding:6px 10px;background:#f9fafb;border-left:3px solid #d1d5db;'
                    f'border-radius:0 4px 4px 0;margin:4px 0 10px;">'
                    f'"{excerpt[:400]}"</div>',
                    unsafe_allow_html=True,
                )


def _finding_card(
    finding,
    claim_id: str,
    reviewer_name: str,
    repo: AuditRepository,
    retrieved_policies: list[dict] | None = None,
) -> None:
    fid = finding.finding_id
    style = _SEVERITY_STYLE.get(finding.severity, {"border": "#6b7280", "card_bg": "#f9fafb"})

    st.markdown(
        f'<div style="border-left:4px solid {style["border"]};'
        f'background:{style["card_bg"]};padding:12px 16px;'
        f'border-radius:0 6px 6px 0;margin-bottom:4px;">'
        f'{_severity_badge(finding.severity)}'
        f'{_source_badge(finding)}'
        f'&nbsp;&nbsp;<strong>{finding.issue}</strong>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.container():
        col_detail, col_action = st.columns([3, 1])

        with col_detail:
            why = _why_it_matters(finding)
            if why:
                st.caption(f"💡 {why}")
            st.write(f"**Recommendation:** {finding.recommendation}")
            st.caption(
                f"Citation: {_citation_caption(finding.citation)} &nbsp;|&nbsp; "
                f"Confidence: {finding.confidence:.0%}"
            )
            if _citation_is_json_fallback(finding.citation, retrieved_policies):
                st.caption(
                    "📁 Policy context: curated JSON fallback corpus — the vector "
                    "store was empty, unseeded, or unavailable for this claim."
                )
            if finding.confidence < CONFIDENCE_REVIEW_THRESHOLD:
                st.caption("⚠️ **Manual Review Recommended** — confidence below 70%")
            with st.expander("📄 View policy detail"):
                _render_citation_detail(finding.citation)
            if retrieved_policies:
                _render_supporting_policies(retrieved_policies, finding.citation.doc_id)

        with col_action:
            decision_key = f"decision_{fid}"
            reason_key = f"reason_{fid}"
            text_area_key = f"reason_input_{fid}"
            saved_key = f"saved_{fid}"

            user_decision = st.session_state.get(decision_key)

            if user_decision is None:
                btn_col1, btn_col2 = st.columns(2)
                if btn_col1.button("✓ Accept", key=f"accept_{fid}", use_container_width=True):
                    st.session_state[decision_key] = "accepted"
                    st.rerun()
                if btn_col2.button("✗ Override", key=f"override_{fid}", use_container_width=True):
                    st.session_state[decision_key] = "override_pending"
                    st.rerun()

            elif user_decision == "override_pending":
                reason = st.text_area(
                    "Override reason (required)",
                    key=text_area_key,
                    height=80,
                    placeholder="Explain why you are overriding this finding…",
                )
                if st.button("Confirm", key=f"confirm_{fid}"):
                    if reason.strip():
                        st.session_state[reason_key] = reason.strip()
                        st.session_state[decision_key] = "overridden"
                        st.rerun()
                    else:
                        st.warning("Please enter a reason before confirming.")

            elif user_decision == "accepted":
                st.success("✓ Accepted")
                _save_controls(fid, finding, claim_id, reviewer_name, user_decision, repo, saved_key, reason_key)

            elif user_decision == "overridden":
                stored_reason = st.session_state.get(reason_key, "")
                st.warning("⚠ Overridden")
                if stored_reason:
                    st.caption(f"Reason: {stored_reason}")
                _save_controls(fid, finding, claim_id, reviewer_name, user_decision, repo, saved_key, reason_key)

    st.divider()


def _save_controls(
    fid: str,
    finding,
    claim_id: str,
    reviewer_name: str,
    user_decision: str,
    repo: AuditRepository,
    saved_key: str,
    reason_key: str,
) -> None:
    if st.session_state.get(saved_key):
        st.caption("✅ Saved to audit log")
        return

    if not reviewer_name.strip():
        st.caption("Enter your name in the header above to save.")
        return

    if st.button("💾 Save Decision", key=f"save_{fid}", use_container_width=True):
        audit_decision = AuditDecision(
            claim_id=claim_id,
            finding_id=finding.finding_id,
            source=finding.source,
            severity=finding.severity,
            issue=finding.issue,
            recommendation=finding.recommendation,
            citation_source=finding.citation.source,
            citation_doc_id=finding.citation.doc_id,
            citation_section=finding.citation.section,
            citation_edition=finding.citation.edition,
            citation_effective_date=finding.citation.effective_date,
            citation_excerpt=finding.citation.excerpt,
            confidence=finding.confidence,
            user_decision=user_decision,
            override_reason=st.session_state.get(reason_key, ""),
            reviewer_name=reviewer_name.strip(),
            model_version=MODEL_VERSION,
            prompt_version=PROMPT_VERSION,
        )
        try:
            repo.save_decision(audit_decision)
            st.session_state[saved_key] = True
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_checks_expander(checks: list[str]) -> None:
    """Collapsed-by-default list of which validation checks ran — same checks
    data as before, just moved out of an always-visible caption to reduce
    visual noise. No change to what's tracked or how it's computed."""
    with st.expander(f"Validation Checks Performed ({len(checks)})"):
        for check in checks:
            st.markdown(f"✓ {check}")


def _render_checks_summary(findings: list) -> None:
    """Always-visible NPI short-circuit warning (if any) + collapsed checks-run detail."""
    npi_short_circuited = any(
        f.rule == "npi_invalid" and f.severity == "HIGH" for f in findings
    )
    if npi_short_circuited:
        st.caption(
            "⚡ **NPI short-circuit:** invalid NPI stopped evaluation. "
            "Fix the NPI to run NCCI, MUE, and code-validity checks."
        )
        _render_checks_expander([CHECKS_RUN[0]])
    else:
        _render_checks_expander(CHECKS_RUN)


def _run_full_review_safely(claim):
    """
    Call agents.orchestrator.run_review() and surface any unexpected failure
    as a visible st.error() instead of an unhandled Streamlit exception.

    The orchestrator and both agents already degrade individual check
    failures (API errors, malformed model responses) to "no finding" — this
    is a last-resort guard for anything still unaccounted for (e.g. a bug in
    synthesis), so a single bad claim can never blank-screen the app for any
    claim source, demo or manual.

    Returns (assessment, retrieved_policies) on success, or (None, None) on
    failure after showing the error.
    """
    try:
        return run_review(claim)
    except Exception as exc:
        logging.getLogger(__name__).exception("Full review failed for claim %s", claim.claim_id)
        st.error(
            f"⚠️ Full review could not complete due to an unexpected error: {exc}\n\n"
            "Deterministic rule-engine review is still available via "
            "\"Review Claim (rule layer only)\"."
        )
        return None, None


def _render_full_review_results(
    risk_assessment,
    claim_id: str,
    reviewer_name: str,
    repo: AuditRepository,
    retrieved_policies: dict[str, list[dict]] | None = None,
) -> None:
    """Render a RiskAssessment from agents.orchestrator.run_review() — one consolidated findings list.

    retrieved_policies (TD-22, optional): the sibling dict run_review() returns
    alongside the RiskAssessment, mapping "coverage_validation"/"coding_validation"
    to the policies that agent retrieved — used to show "Supporting Policies
    Reviewed" on the matching finding card.
    """
    label, kind = _RISK_CONFIG[risk_assessment.score]
    getattr(st, kind)(label)
    _render_risk_explanation(risk_assessment.score, risk_assessment.findings)

    npi_short_circuited = any(
        f.rule == "npi_invalid" and f.severity == "HIGH" for f in risk_assessment.findings
    )
    if npi_short_circuited:
        st.caption(
            "⚡ **NPI short-circuit:** invalid NPI stopped evaluation before "
            "NCCI, MUE, code-validity, and coverage analysis ran."
        )
    _render_checks_expander(risk_assessment.checks_run)

    if risk_assessment.escalation_required:
        st.warning(
            "⚠️ **Manual Review Recommended** — one or more findings have confidence "
            "below 70%. Escalate for human review before submission."
        )

    if risk_assessment.findings:
        st.subheader(f"Findings ({len(risk_assessment.findings)})")
        for finding in risk_assessment.findings:
            policies_for_finding = (retrieved_policies or {}).get(finding.rule)
            _finding_card(
                finding,
                claim_id=claim_id,
                reviewer_name=reviewer_name,
                repo=repo,
                retrieved_policies=policies_for_finding,
            )
    else:
        st.success("✅ No findings — rule checks and coverage analysis found no denial risk indicators.")


def _render_ai_section(claim, claim_id: str, reviewer_name: str, repo: AuditRepository) -> None:
    """Render the AI Coverage Analysis button and its findings below rule results."""
    if not _AI_ENABLED:
        st.divider()
        st.warning(
            "⚠️ **AI Agents Disabled**\n\n"
            "Use the ⚙️ icon next to the AI status pill to enable AI for this browser "
            "session, or ask the app owner to configure an API key.\n\n"
            "Deterministic rule-engine review remains available."
        )
        return

    st.divider()
    st.subheader("AI Coverage Analysis")

    if not st.session_state.get("ai_reviewed"):
        st.caption(
            "Run AI-powered coverage and medical necessity analysis against "
            "retrieved LCD/NCD policy documents."
        )
        if st.button("🤖 Run AI Coverage Analysis", key=f"ai_btn_{claim_id}"):
            with st.spinner("Querying policy documents and analyzing coverage…"):
                ai_findings, ai_policies = validate_coverage(claim)
            st.session_state["ai_findings"] = ai_findings
            st.session_state["ai_policies"] = ai_policies
            st.session_state["ai_reviewed"] = True
            st.rerun()
    else:
        ai_findings = st.session_state.get("ai_findings", [])
        ai_policies = st.session_state.get("ai_policies", [])
        if ai_findings:
            st.caption(f"{len(ai_findings)} finding(s) from AI coverage analysis.")
            for finding in ai_findings:
                _finding_card(
                    finding,
                    claim_id=claim_id,
                    reviewer_name=reviewer_name,
                    repo=repo,
                    retrieved_policies=ai_policies,
                )
        else:
            st.success("✅ No coverage concerns identified by AI analysis.")

        if st.button("↩ Clear AI Analysis", key=f"ai_clear_{claim_id}"):
            st.session_state.pop("ai_findings", None)
            st.session_state.pop("ai_policies", None)
            st.session_state.pop("ai_reviewed", None)
            st.rerun()


def _render_cached_ai_demo(claim_id: str) -> None:
    """
    When AI is disabled (no ANTHROPIC_API_KEY), show pre-generated AI findings for
    designated sample claims so public users can preview representative agent
    output. Read-only — no Accept/Override/Save, since these findings were not
    produced by a live run of this session. Never shown when AI is enabled; the
    live agents always take priority over cached artifacts.
    """
    if _AI_ENABLED:
        return

    cached_findings = _cached_ai_findings_for(claim_id)
    if not cached_findings:
        return

    st.divider()
    st.info(
        "📋 **Pre-generated demonstration results** — AI is currently disabled "
        "(no `ANTHROPIC_API_KEY`). The findings below were captured in advance "
        "from a real run of the Coverage and Coding agents against this sample "
        "claim, so you can preview representative AI output without making a "
        "live API call. Provide your own key to run live AI analysis instead."
    )
    for finding in cached_findings:
        style = _SEVERITY_STYLE.get(finding.severity, {"border": "#6b7280", "card_bg": "#f9fafb"})
        st.markdown(
            f'<div style="border-left:4px solid {style["border"]};'
            f'background:{style["card_bg"]};padding:12px 16px;'
            f'border-radius:0 6px 6px 0;margin-bottom:4px;">'
            f'{_severity_badge(finding.severity)}'
            f'{_source_badge(finding)}'
            f'&nbsp;&nbsp;<strong>{finding.issue}</strong>'
            f'</div>',
            unsafe_allow_html=True,
        )
        why = _why_it_matters(finding)
        if why:
            st.caption(f"💡 {why}")
        st.write(f"**Recommendation:** {finding.recommendation}")
        st.caption(
            f"Citation: {_citation_caption(finding.citation)} &nbsp;|&nbsp; "
            f"Confidence: {finding.confidence:.0%}"
        )
        with st.expander("📄 View policy detail"):
            _render_citation_detail(finding.citation)
        st.divider()


def _clear_review_state() -> None:
    keys_to_clear = [
        k for k in st.session_state
        if k.startswith(("decision_", "reason_", "saved_", "reason_input_"))
    ]
    for k in keys_to_clear:
        del st.session_state[k]
    for key in (
        "findings", "risk", "reviewed_claim_id",
        "manual_reviewed", "manual_claim_dict",
        "ai_findings", "ai_policies", "ai_reviewed",
        "full_review_assessment", "full_review_retrieved_policies",
        "full_review_claim_id", "full_review_claim_dict",
    ):
        st.session_state.pop(key, None)


def _render_audit_trail(repo: AuditRepository) -> None:
    st.subheader("Saved Decisions")

    col1, col2 = st.columns(2)
    claim_filter = col1.text_input("Filter by Claim ID", key="audit_claim_filter")
    reviewer_filter = col2.text_input("Filter by Reviewer", key="audit_reviewer_filter")

    decisions = repo.get_decisions(
        claim_id=claim_filter.strip() or None,
        reviewer_name=reviewer_filter.strip() or None,
    )

    if not decisions:
        st.info("No decisions saved yet. Review a claim and save decisions to see them here.")
        return

    st.write(f"**{len(decisions)} decision(s)**")

    df = pd.DataFrame(decisions)
    display_cols = [
        "timestamp", "claim_id", "finding_id", "severity", "user_decision",
        "reviewer_name", "confidence", "issue", "override_reason",
        "citation_source", "citation_doc_id", "citation_section", "citation_effective_date",
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(df[display_cols], use_container_width=True)


# ---------------------------------------------------------------------------
# Manual mode callbacks (module-level so Streamlit can serialize them)
# ---------------------------------------------------------------------------

def _form_version() -> int:
    return st.session_state.get("manual_form_version", 0)


def _mkey(field: str) -> str:
    """Versioned key for a manual-entry header field widget.

    Deleting a text_input's session_state key does not reliably reset its
    displayed value in the browser (confirmed: the frontend keeps showing the
    stale value even though session_state is correctly cleared server-side).
    Giving the widget a brand-new key — by bumping manual_form_version on
    Clear Form / Start from a template — forces a fresh widget instance with
    no stale value, which does reset reliably.
    """
    return f"manual_{field}_v{_form_version()}"


def _slkey(row_id: int, field: str) -> str:
    return f"sl_{_form_version()}_{row_id}_{field}"


def _on_payer_name_change() -> None:
    name = st.session_state.get(_mkey("payer_name"), "")
    st.session_state[_mkey("payer_id")] = get_payer_id(name)


def _clear_manual_form() -> None:
    next_version = _form_version() + 1
    keys_to_clear = [k for k in st.session_state if k.startswith(("manual_", "sl_"))]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state["manual_form_version"] = next_version
    _clear_review_state()


def _load_worked_example() -> None:
    _clear_manual_form()
    ex = WORKED_EXAMPLE
    st.session_state[_mkey("claim_id")] = ex["claim_id"]
    st.session_state[_mkey("payer_name")] = ex["payer_name"]
    st.session_state[_mkey("payer_id")] = get_payer_id(ex["payer_name"])
    st.session_state[_mkey("specialty")] = ex["provider_specialty"]
    st.session_state[_mkey("npi")] = ex["npi"]
    st.session_state[_mkey("note_text")] = ex["note_text"]
    row_ids = list(range(len(ex["service_lines"])))
    st.session_state["manual_active_rows"] = row_ids
    st.session_state["manual_next_row_id"] = len(ex["service_lines"])
    for row_id, line in zip(row_ids, ex["service_lines"]):
        for field in ("cpt", "mod1", "mod2", "icd10_1", "icd10_2", "icd10_3", "icd10_4"):
            st.session_state[_slkey(row_id, field)] = line[field]
        st.session_state[_slkey(row_id, "units")] = line.get("units", 1)


def _collect_manual_claim_dict_or_errors() -> tuple[dict | None, list[str]]:
    """
    Build a claim_dict from manual-entry session state, validating along the way.

    Returns (claim_dict, []) on success or (None, errors) on validation failure.
    Shared by both the unified "Run Full Review" button and the rule-layer-only
    "Review Claim" button so the same validation runs regardless of which is used.
    """
    header = {
        "claim_id": st.session_state.get(_mkey("claim_id"), "").strip(),
        "payer_name": st.session_state.get(_mkey("payer_name"), ""),
        "payer_id": st.session_state.get(_mkey("payer_id"), "").strip(),
        "npi": st.session_state.get(_mkey("npi"), "").strip(),
        "provider_specialty": st.session_state.get(_mkey("specialty"), "").strip(),
        "note_text": st.session_state.get(_mkey("note_text"), "").strip(),
    }

    lines = [
        {
            "cpt": st.session_state.get(_slkey(row_id, "cpt"), ""),
            "mod1": st.session_state.get(_slkey(row_id, "mod1"), ""),
            "mod2": st.session_state.get(_slkey(row_id, "mod2"), ""),
            "units": st.session_state.get(_slkey(row_id, "units"), 1),
            "icd10_1": st.session_state.get(_slkey(row_id, "icd10_1"), ""),
            "icd10_2": st.session_state.get(_slkey(row_id, "icd10_2"), ""),
            "icd10_3": st.session_state.get(_slkey(row_id, "icd10_3"), ""),
            "icd10_4": st.session_state.get(_slkey(row_id, "icd10_4"), ""),
        }
        for row_id in st.session_state["manual_active_rows"]
    ]

    errors: list[str] = []
    if not header["claim_id"]:
        errors.append("Claim ID is required.")
    payer_val = header["payer_name"]
    if not payer_val or payer_val == _PAYER_PLACEHOLDER:
        errors.append("Payer is required.")
    npi_ok, npi_err = validate_npi(header["npi"])
    if not npi_ok:
        errors.append(f"NPI: {npi_err}")
    cpts_entered = [normalize_code(l["cpt"]) for l in lines if l["cpt"].strip()]
    if not cpts_entered:
        errors.append("At least one CPT/HCPCS code is required.")

    if errors:
        return None, errors

    return build_manual_claim(header, lines), []


# ---------------------------------------------------------------------------
# Manual Claim Entry UI
# ---------------------------------------------------------------------------

def _render_manual_mode(reviewer_name: str, repo: AuditRepository) -> None:
    # Init service-line tracking if not present (also re-initializes after Clear Form)
    if "manual_active_rows" not in st.session_state:
        st.session_state["manual_active_rows"] = [0]
        st.session_state["manual_next_row_id"] = 1

    # Default payer to Medicare — the coverage policy corpus (LCDs/NCDs) is
    # Medicare-administrative-contractor policy, and payer otherwise has no
    # effect on rule-layer or retrieval behavior (see caption below).
    if _mkey("payer_name") not in st.session_state:
        st.session_state[_mkey("payer_name")] = "Medicare"
        st.session_state[_mkey("payer_id")] = get_payer_id("Medicare")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.text_input(
            "Claim ID *",
            key=_mkey("claim_id"),
            placeholder="CLM-MANUAL-001",
        )
    with col2:
        payer_options = [_PAYER_PLACEHOLDER] + list(PAYER_ID_MAP.keys())
        st.selectbox(
            "Payer *",
            options=payer_options,
            key=_mkey("payer_name"),
            on_change=_on_payer_name_change,
        )
    with col3:
        st.text_input(
            "Payer ID",
            key=_mkey("payer_id"),
            placeholder="Auto-populated from payer selection",
        )
    st.caption(
        "Payer doesn't change rule-layer findings or which policies are retrieved today — "
        "it's shown to the AI agents as context only."
    )

    col4, col5 = st.columns(2)
    with col4:
        st.text_input(
            "Provider NPI (optional)",
            key=_mkey("npi"),
            placeholder="10-digit NPI number",
            max_chars=10,
            help="Format validated here. Luhn check-digit and NPPES registry lookup run at review time.",
        )
    with col5:
        st.text_input(
            "Provider Specialty (optional)",
            key=_mkey("specialty"),
            placeholder="e.g. Internal Medicine",
        )

    st.text_area(
        "Clinical Notes (optional)",
        key=_mkey("note_text"),
        placeholder="Paste de-identified clinical documentation here…",
        height=80,
    )
    st.caption("⚠️ Do not enter PHI. Synthetic or de-identified notes only.")

    st.divider()

    # ---- Service-Line Coding Grid ----
    st.markdown("#### Service Lines")

    hdr_cols = st.columns(_SL_COLS)
    for col, hdr in zip(hdr_cols, _SL_HEADERS):
        if hdr:
            col.markdown(f"**{hdr}**")

    active_rows: list[int] = st.session_state["manual_active_rows"]
    rows_to_remove: list[int] = []

    for row_id in active_rows:
        cols = st.columns(_SL_COLS)
        cols[0].text_input("CPT", key=_slkey(row_id, "cpt"), label_visibility="collapsed", placeholder="99213")
        cols[1].text_input("Mod1", key=_slkey(row_id, "mod1"), label_visibility="collapsed", placeholder="25")
        cols[2].text_input("Mod2", key=_slkey(row_id, "mod2"), label_visibility="collapsed", placeholder="")
        cols[3].number_input("Units", key=_slkey(row_id, "units"), min_value=1, max_value=999, label_visibility="collapsed")
        cols[4].text_input("ICD1", key=_slkey(row_id, "icd10_1"), label_visibility="collapsed", placeholder="Z00.00")
        cols[5].text_input("ICD2", key=_slkey(row_id, "icd10_2"), label_visibility="collapsed", placeholder="")
        cols[6].text_input("ICD3", key=_slkey(row_id, "icd10_3"), label_visibility="collapsed", placeholder="")
        cols[7].text_input("ICD4", key=_slkey(row_id, "icd10_4"), label_visibility="collapsed", placeholder="")
        if len(active_rows) > 1:
            if cols[8].button("✕", key=f"sl_rm_{row_id}", help="Remove this service line"):
                rows_to_remove.append(row_id)

    if rows_to_remove:
        st.session_state["manual_active_rows"] = [r for r in active_rows if r not in rows_to_remove]
        _clear_review_state()
        st.rerun()

    # Add / Clear / Load buttons
    btn_add, btn_clear, btn_example, _ = st.columns([1.5, 1.2, 1.8, 4])
    if btn_add.button("➕ Add Service Line", key="manual_add_sl"):
        next_id = st.session_state["manual_next_row_id"]
        st.session_state["manual_active_rows"].append(next_id)
        st.session_state["manual_next_row_id"] = next_id + 1
        st.rerun()

    btn_clear.button("🗑 Clear Form", key="manual_clear_btn", on_click=_clear_manual_form)
    btn_example.button("📋 Start from a template", key="manual_example_btn", on_click=_load_worked_example)

    st.divider()
    st.markdown("<div style='height:22px'></div>", unsafe_allow_html=True)

    # ---- Review buttons, side by side ----
    btn_full, btn_rule = st.columns(2)
    with btn_full:
        run_full_clicked = st.button(
            "🚀 Run Full Review", type="primary", key="manual_full_review_btn", use_container_width=True
        )
    with btn_rule:
        run_rule_clicked = st.button(
            "🔍 Review Claim (rule layer only)", type="secondary", key="manual_review_btn", use_container_width=True
        )

    if run_full_clicked:
        claim_dict, errors = _collect_manual_claim_dict_or_errors()
        if errors:
            for err in errors:
                st.error(err)
        else:
            _clear_review_state()
            claim = load_claim(claim_dict)
            assessment, retrieved_policies = _run_full_review_safely(claim)
            if assessment is not None:
                st.session_state["full_review_assessment"] = assessment
                st.session_state["full_review_retrieved_policies"] = retrieved_policies
                st.session_state["full_review_claim_id"] = claim_dict["claim_id"]
                st.session_state["full_review_claim_dict"] = claim_dict

    if "full_review_assessment" in st.session_state and st.session_state.get("full_review_claim_dict"):
        _render_full_review_results(
            st.session_state["full_review_assessment"],
            claim_id=st.session_state["full_review_claim_id"],
            reviewer_name=reviewer_name,
            repo=repo,
            retrieved_policies=st.session_state.get("full_review_retrieved_policies"),
        )

    if run_rule_clicked:
        claim_dict, errors = _collect_manual_claim_dict_or_errors()
        if errors:
            for err in errors:
                st.error(err)
        else:
            _clear_review_state()
            claim = load_claim(claim_dict)
            findings = review_claim(claim)
            risk = overall_risk(findings)
            st.session_state["findings"] = findings
            st.session_state["risk"] = risk
            st.session_state["reviewed_claim_id"] = claim_dict["claim_id"]
            st.session_state["manual_reviewed"] = True
            st.session_state["manual_claim_dict"] = claim_dict

    # ---- Findings display ----
    if st.session_state.get("manual_reviewed"):
        findings = st.session_state["findings"]
        risk = st.session_state["risk"]
        reviewed_id = st.session_state.get("reviewed_claim_id", "")

        label, kind = _RISK_CONFIG[risk]
        getattr(st, kind)(label)
        _render_risk_explanation(risk, findings)
        _render_checks_summary(findings)

        if findings:
            st.subheader(f"Findings ({len(findings)})")
            for finding in findings:
                _finding_card(
                    finding,
                    claim_id=reviewed_id,
                    reviewer_name=reviewer_name,
                    repo=repo,
                )

        stored_dict = st.session_state.get("manual_claim_dict")
        if stored_dict:
            _render_ai_section(
                claim=load_claim(stored_dict),
                claim_id=reviewed_id,
                reviewer_name=reviewer_name,
                repo=repo,
            )


# ---------------------------------------------------------------------------
# Sample Claim UI (existing mode, unchanged)
# ---------------------------------------------------------------------------

def _render_sample_mode(reviewer_name: str, repo: AuditRepository) -> None:
    claims = load_claims()
    claim_labels = [
        f"{c['claim_id']} — {c['description']}  ·  {c.get('demo_type', '')}"
        for c in claims
    ]

    jump_to = st.session_state.pop("_jump_to_claim", None)
    if jump_to:
        for label, c in zip(claim_labels, claims):
            if c["claim_id"] == jump_to:
                st.session_state["sample_claim_select"] = label
                break

    selected_label = st.selectbox(
        "Select a demo scenario", claim_labels, key="sample_claim_select"
    )
    selected_idx = claim_labels.index(selected_label)
    claim_dict = claims[selected_idx]

    if st.session_state.get("selected_claim_id") != claim_dict["claim_id"]:
        _clear_review_state()
        st.session_state["selected_claim_id"] = claim_dict["claim_id"]

    with st.expander("Claim Details", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Claim ID:** {claim_dict['claim_id']}")
            st.write(f"**Payer:** {claim_dict['payer']}")
            npi_display = claim_dict.get("npi") or "Not provided"
            st.write(f"**NPI:** {npi_display}")
            st.write(f"**Place of Service:** {claim_dict['place_of_service']}")
        with col2:
            st.write(f"**CPT / HCPCS codes:** {', '.join(claim_dict['cpt_codes'])}")
            st.write(f"**ICD-10 diagnoses:** {', '.join(claim_dict['icd10_codes'])}")
            mods = ", ".join(claim_dict.get("modifiers", [])) or "None"
            st.write(f"**Modifiers:** {mods}")

    st.divider()
    st.markdown("<div style='height:22px'></div>", unsafe_allow_html=True)

    btn_full, btn_rule = st.columns(2)
    with btn_full:
        run_full_clicked = st.button(
            "🚀 Run Full Review", type="primary", key="sample_full_review_btn", use_container_width=True
        )
    with btn_rule:
        run_rule_clicked = st.button(
            "🔍 Review Claim (rule layer only)", type="secondary", key="sample_review_btn", use_container_width=True
        )

    if run_full_clicked:
        _clear_review_state()
        claim = load_claim(claim_dict)
        assessment, retrieved_policies = _run_full_review_safely(claim)
        if assessment is not None:
            st.session_state["full_review_assessment"] = assessment
            st.session_state["full_review_retrieved_policies"] = retrieved_policies
            st.session_state["full_review_claim_id"] = claim_dict["claim_id"]

    if (
        "full_review_assessment" in st.session_state
        and st.session_state.get("full_review_claim_id") == claim_dict["claim_id"]
    ):
        _render_full_review_results(
            st.session_state["full_review_assessment"],
            claim_id=claim_dict["claim_id"],
            reviewer_name=reviewer_name,
            repo=repo,
            retrieved_policies=st.session_state.get("full_review_retrieved_policies"),
        )
        _render_cached_ai_demo(claim_dict["claim_id"])

    if run_rule_clicked:
        _clear_review_state()
        claim = load_claim(claim_dict)
        findings = review_claim(claim)
        risk = overall_risk(findings)
        st.session_state["findings"] = findings
        st.session_state["risk"] = risk
        st.session_state["reviewed_claim_id"] = claim_dict["claim_id"]
        st.session_state["sample_claim_dict"] = claim_dict

    if (
        "findings" in st.session_state
        and st.session_state.get("reviewed_claim_id") == claim_dict["claim_id"]
    ):
        findings = st.session_state["findings"]
        risk = st.session_state["risk"]

        label, kind = _RISK_CONFIG[risk]
        getattr(st, kind)(label)
        _render_risk_explanation(risk, findings)
        _render_checks_summary(findings)

        if findings:
            st.subheader(f"Findings ({len(findings)})")
            for finding in findings:
                _finding_card(
                    finding,
                    claim_id=claim_dict["claim_id"],
                    reviewer_name=reviewer_name,
                    repo=repo,
                )

        stored_dict = st.session_state.get("sample_claim_dict", claim_dict)
        _render_ai_section(
            claim=load_claim(stored_dict),
            claim_id=stored_dict["claim_id"],
            reviewer_name=reviewer_name,
            repo=repo,
        )
        _render_cached_ai_demo(stored_dict["claim_id"])


# ---------------------------------------------------------------------------
# Header bar, landing state, Getting Started dialog
# ---------------------------------------------------------------------------

def _pill(text: str, bg: str, font_size: str = "0.78rem", padding: str = "3px 10px") -> str:
    return (
        f'<span style="background:{bg};color:#fff;padding:{padding};'
        f'border-radius:12px;font-size:{font_size};font-weight:600;'
        f'white-space:nowrap;">{text}</span>'
    )


_DATA_STATUS_LABELS = {
    "file_backed": ("🟢 Data: Live CMS", "Live CMS"),
    "synthetic_fallback": ("🟡 Data: Synthetic fallback", "Synthetic fallback"),
    "mixed": ("🟡 Data: Mixed", "Mixed"),
    "not_checked": ("⚪ Data: Not Refreshed", "Not Refreshed"),
}

_SESSION_API_KEY_NAME = "ANTHROPIC_API_KEY"


def _render_session_api_key_popover() -> None:
    """
    Small gear-icon popover letting a user provide their own Anthropic API key
    for this browser session only. The key is stored solely in
    st.session_state (never written to disk, never logged, never sent to the
    audit DB) under the same name agents.secrets.get_secret() checks first —
    see that module for the full resolution order. Closing or refreshing the
    browser tab ends the session and the key with it.
    """
    with st.popover("⚙️", help="API key settings"):
        st.caption(
            "Live Coverage and Coding agents require an Anthropic API key. "
            "You may provide your own key for this browser session. The key "
            "is not stored or persisted."
        )
        session_key_input = st.text_input(
            "Anthropic API Key",
            type="password",
            key="session_api_key_input",
            placeholder="sk-ant-...",
        )
        col_enable, col_clear = st.columns(2)
        with col_enable:
            if st.button("Enable AI", key="enable_session_api_key_btn", use_container_width=True):
                if session_key_input:
                    st.session_state[_SESSION_API_KEY_NAME] = session_key_input
                    st.rerun()
        with col_clear:
            if st.button("Clear Key", key="clear_session_api_key_btn", use_container_width=True):
                st.session_state.pop(_SESSION_API_KEY_NAME, None)
                st.rerun()
        st.caption("Used only for this browser session. Not stored or persisted.")


def _render_header() -> str:
    """Renders the title/badge row and the reviewer/AI/data-source/help controls
    row. Returns the reviewer name. Replaces the old st.sidebar entirely.

    The Data Source status is entirely user-initiated, mirroring the gear-icon
    session API key control's UX: no check, no CMS asset download, and no
    rerun happens on page load. The Data pill defaults to a neutral "Not
    Refreshed" state; rules.data_source_status is only computed when the user
    clicks "Check CMS Data Availability" inside the pill's popover, and the
    resolved result is cached in st.session_state for the rest of the browser
    session (or until "Refresh Data Status" is clicked) — no calculation
    logic changed, only when it runs.
    """
    data_source_ready = st.session_state.get("_data_source_ready", False)
    summary = st.session_state.get("_data_source_summary_cache") if data_source_ready else None

    col_title, col_badge = st.columns([4, 2])
    with col_title:
        st.markdown("## 🏥 Denial Prevention Copilot")
        st.caption("AI researches. Humans decide.")
    with col_badge:
        st.markdown(
            f'<div style="text-align:right;padding-top:26px;">'
            f'{_pill("Portfolio Project · Synthetic Data Only", "#1e3a8a", font_size="1.0rem", padding="5px 14px")}'
            f'</div>',
            unsafe_allow_html=True,
        )

    with st.container(key="header_controls_row"):
        c_reviewer, c_ai, c_gear, c_data, c_help = st.columns([2.2, 0.85, 0.45, 1.6, 0.5])
        with c_reviewer:
            reviewer_name = st.text_input(
                "Reviewer",
                key="reviewer_name",
                placeholder="Your name (required to save decisions)",
            )
        with c_ai:
            if _AI_ENABLED:
                st.markdown(
                    f'<div style="margin-bottom:25px;">'
                    f'{_pill("● AI: Enabled", "#16a34a", font_size="0.92rem", padding="5px 12px")}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="margin-bottom:25px;">'
                    f'{_pill("● AI: Disabled", "#6b7280", font_size="0.92rem", padding="5px 12px")}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        with c_gear:
            with st.container(key="ai_gear_col"):
                _render_session_api_key_popover()
        with c_data:
            label, _ = _DATA_STATUS_LABELS[summary["overall"] if summary is not None else "not_checked"]
            with st.popover(label):
                if summary is None:
                    st.caption(
                        "CMS data status is not checked automatically — this app never "
                        "downloads or parses CMS reference files until you ask it to."
                    )
                    if st.button("🔍 Check CMS Data Availability", key="check_cms_data_btn", use_container_width=True):
                        with st.spinner("Checking CMS data availability…"):
                            st.session_state["_data_source_summary_cache"] = _data_source_summary()
                            st.session_state["_data_source_ready"] = True
                        st.rerun()
                else:
                    st.caption(
                        "Reference data backing the deterministic rule layer. Synthetic "
                        "fallback tables are curated to behave correctly for the demo "
                        "scenarios — they are smaller, not less accurate for this app."
                    )
                    for name, info in summary["datasets"].items():
                        state = "🟢 file-backed" if info["status"] == "file_backed" else "🟡 synthetic fallback"
                        st.markdown(f"**{name.upper()}** — {state}")
                        if info.get("version"):
                            st.caption(f"Version: {info['version']}" + (f" · effective {info['effective_date']}" if info.get("effective_date") else ""))
                        source = info.get("source")
                        if source == "downloaded":
                            st.caption("📥 Downloaded from a configured GitHub Release Asset.")
                        elif info.get("download_attempted") and info.get("download_error"):
                            st.caption(f"⚠️ Download attempted but failed ({info['download_error']}) — using fallback.")
                    st.divider()
                    if st.button("🔄 Refresh Data Status", key="refresh_cms_data_btn", use_container_width=True):
                        # Clear every layer that's memoized per-process (not just this
                        # function's own cache_resource) — otherwise re-checking after
                        # updating secrets or deploying new CMS assets would just
                        # re-display the same stale result these caches already hold.
                        # Existing test-only helpers, reused as-is — no new cache-
                        # invalidation logic written for this.
                        _data_source_summary.clear()
                        ncci_loader._clear_ncci_cache()
                        mue_loader._clear_mue_cache()
                        icd10_loader._clear_icd10_cache()
                        cms_asset_fetch._clear_cms_asset_cache()
                        with st.spinner("Checking CMS data availability…"):
                            st.session_state["_data_source_summary_cache"] = _data_source_summary()
                            st.session_state["_data_source_ready"] = True
                        st.rerun()
                    st.caption("Useful after updating secrets, deploying new CMS assets, or testing in a different environment.")
        with c_help:
            if st.button("❔", key="help_btn", help="Getting Started", type="primary"):
                _getting_started_dialog()

    st.markdown(
        "<style>"
        "div[class*='st-key-header_controls_row'] div[data-testid='stHorizontalBlock']"
        "{ align-items: flex-end; }"
        "div[class*='st-key-ai_gear_col']"
        "{ position: relative; left: 60px; }"
        "</style>",
        unsafe_allow_html=True,
    )

    return reviewer_name


@st.dialog("Getting Started", width="large")
def _getting_started_dialog() -> None:
    st.markdown(
        "**Denial Prevention Copilot** reviews a healthcare claim *before* it's "
        "submitted and flags issues that commonly cause payer denials — bundling "
        "conflicts, unit limits, missing modifiers, invalid codes, and medical "
        "necessity / coverage concerns."
    )

    st.markdown("#### How it works")
    st.code(
        "Claim → Rule Engine → Coverage Agent + Coding Agent → Risk Assessment → Human Review → Audit Trail",
        language=None,
    )
    st.markdown(
        "- **Rule Engine** — deterministic checks (NCCI bundling, MUE unit limits, "
        "NPI validity, ICD-10/CPT code validity, missing modifiers). Always runs, no API key needed.\n"
        "- **Coverage Agent** / **Coding Agent** — LLM-backed, citation-grounded checks "
        "against real LCD/NCD policy text. Require your own `ANTHROPIC_API_KEY`."
    )

    st.markdown("#### AI status you'll see in this app")
    st.markdown(
        "- **● AI: Enabled** — an API key is configured (by the app owner, or by you via "
        "the ⚙️ icon next to the pill for this browser session); Coverage/Coding agents run live.\n"
        "- **● AI: Disabled** — no key configured; only the deterministic Rule Engine runs. "
        "Click the ⚙️ icon to add your own key for this session.\n"
        "- **📋 Pre-generated demonstration results** — shown per-claim for select demo "
        "scenarios when AI is disabled, so you can preview real agent output without an API call."
    )

    st.markdown("#### Confidence")
    st.markdown(
        "- Confidence reflects the system's certainty in a finding — it is **not** "
        "a denial/approval guarantee.\n"
        "- Findings below 70% confidence trigger a manual-review flag.\n"
        "- AI confidence is not a substitute for coding or compliance judgment."
    )

    st.markdown("#### Limitations")
    st.markdown(
        "- **Synthetic data only** — no PHI, no real claims.\n"
        "- **Not for clinical or billing use.** This is a prototype demonstrating an "
        "architecture pattern, not production healthcare software. It has not been "
        "validated against real claims, real payer adjudication, or real patient data.\n"
        "- Human review is required before any claim decision."
    )

    with st.expander("About This Project"):
        st.markdown(
            "**Why was this built?**\n\n"
            "Healthcare organizations often discover coding, coverage, and policy "
            "issues *after* claim submission. This project explores how "
            "deterministic rules, AI-assisted policy review, and human oversight "
            "can work together to identify denial risk earlier."
        )

    with st.expander("What Changed (Release Notes)"):
        st.markdown(
            "**MVP (V1) — Denial Prevention Copilot**\n\n"
            "Initial public demo release focused on AI-assisted claim review and "
            "denial risk identification using synthetic data.\n\n"
            "**Includes:**\n"
            "- Deterministic rule engine for NPI, NCCI, MUE, ICD-10, HCPCS, modifier, "
            "and diagnosis-procedure checks\n"
            "- Coverage Validation Agent\n"
            "- Coding Validation Agent\n"
            "- Unified Risk Assessment\n"
            "- Human Accept / Override workflow\n"
            "- Audit Trail\n"
            "- Citation grounding\n"
            "- Supporting Policies Reviewed\n"
            "- Cached AI demo scenarios\n"
            "- AI Disabled mode\n"
            "- Data Source status indicator\n"
            "- Getting Started guidance\n"
            "- Optional Live CMS rule-layer data: hosted deployments can automatically "
            "download real NCCI/MUE/ICD-10 reference datasets from maintainer-configured "
            "GitHub Release Assets when available, with graceful fallback to synthetic "
            "datasets when not\n\n"
            "**Notes:**\n"
            "- Synthetic data only\n"
            "- Not for clinical or billing use\n"
            "- Not production healthcare software\n"
            "- Live AI features require Anthropic API configuration\n"
            "- Audit history is demo-local and may reset on hosted deployments"
        )

    if st.button("Close"):
        st.rerun()


def _render_recommended_shortcuts(claims: list[dict]) -> None:
    """Shown only under 'Pick a demo scenario', before a review has run."""
    recommended_ids = ["CLM-001", "CLM-005", "CLM-003"]
    by_id = {c["claim_id"]: c for c in claims}
    recommended = [by_id[cid] for cid in recommended_ids if cid in by_id]

    if recommended:
        st.caption("Recommended:")
        cols = st.columns(len(recommended))
        for col, c in zip(cols, recommended):
            with col:
                if st.button(c.get("demo_type", c["claim_id"]), key=f"landing_{c['claim_id']}", use_container_width=True):
                    st.session_state["_jump_to_claim"] = c["claim_id"]
                    st.rerun()


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Denial Prevention Copilot",
        page_icon="💵",
        layout="wide",
    )

    st.markdown(
        "<style>"
        ".block-container{padding-top:2.5rem;padding-bottom:1rem;}"
        "hr{margin:0.5rem 0 !important;}"
        "div[data-testid='stVerticalBlock']{gap:0.6rem;}"
        "</style>",
        unsafe_allow_html=True,
    )

    repo = get_repo()
    reviewer_name = _render_header()
    st.divider()

    tab_review, tab_audit = st.tabs(["🔍 Claim Review", "📋 Audit Trail"])

    with tab_review:
        st.markdown("#### Claim Details")

        mode = st.radio(
            "Claim source",
            options=["Pick a demo scenario", "Enter manually"],
            horizontal=True,
            key="claim_mode",
            label_visibility="collapsed",
        )

        # Clear review state when mode switches
        prev_mode = st.session_state.get("_claim_mode_prev")
        if prev_mode is not None and prev_mode != mode:
            _clear_review_state()
        st.session_state["_claim_mode_prev"] = mode

        has_reviewed = any(
            st.session_state.get(k)
            for k in ("findings", "full_review_assessment", "manual_reviewed")
        )
        if mode == "Pick a demo scenario" and not has_reviewed:
            _render_recommended_shortcuts(load_claims())

        st.divider()

        if mode == "Pick a demo scenario":
            _render_sample_mode(reviewer_name, repo)
        else:
            _render_manual_mode(reviewer_name, repo)

    with tab_audit:
        _render_audit_trail(repo)


if __name__ == "__main__":
    main()
