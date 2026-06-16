"""
Streamlit entry point for the Denial Prevention Copilot.

Responsibilities:
  - Load synthetic claims from data/synthetic/sample_claims.json.
  - Let the user select a claim and display its details.
  - On "Review Claim", call rules.rule_engine — no business logic here.
  - Render findings with color-coded severity badges.
  - Capture per-finding Accept / Override decisions in session state.
  - Persist decisions to SQLite via AuditRepository (never calls sqlite3 directly).
  - Audit Trail tab: view saved decisions, filter, export CSV.

All rule evaluation lives in rules/rule_engine.py.
All DB access goes through db/audit_repository.py.
"""

import json
import pathlib
import sys

# Ensure the project root is on sys.path so `rules` and `db` are importable when
# Streamlit is launched with `streamlit run app/main.py` (Streamlit adds
# the script's directory, not the repo root, to sys.path by default).
_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from rules.rule_engine import load_claim, review_claim, overall_risk
from db.audit_repository import AuditDecision, AuditRepository
from retrieval.policy_repository import get_citation_detail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAIMS_FILE = pathlib.Path(__file__).parent.parent / "data" / "synthetic" / "sample_claims.json"
MODEL_VERSION = "rule_layer_v0.1"
PROMPT_VERSION = "n/a"
CONFIDENCE_REVIEW_THRESHOLD = 0.70

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


# ---------------------------------------------------------------------------
# Cached resources
# ---------------------------------------------------------------------------

@st.cache_data
def load_claims() -> list[dict]:
    with open(CLAIMS_FILE) as f:
        return json.load(f)


@st.cache_resource
def get_repo() -> AuditRepository:
    repo = AuditRepository()
    repo.initialize_database()
    return repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _severity_badge(severity: str) -> str:
    style = _SEVERITY_STYLE.get(severity, {"badge_bg": "#6b7280"})
    return (
        f'<span style="background:{style["badge_bg"]};color:#fff;'
        f'padding:2px 10px;border-radius:4px;font-size:0.72rem;'
        f'font-weight:700;letter-spacing:0.05em;">{severity}</span>'
    )


def _citation_caption(citation) -> str:
    """Build a one-line citation string from a structured Citation object."""
    text = f"{citation.source} — {citation.section}"
    if citation.edition:
        text += f" ({citation.edition})"
    if citation.effective_date:
        text += f" · effective {citation.effective_date}"
    return text


def _render_citation_detail(citation) -> None:
    """Render the full policy detail view for a Citation inside an expander."""
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


def _finding_card(finding, claim_id: str, reviewer_name: str, repo: AuditRepository) -> None:
    fid = finding.finding_id
    style = _SEVERITY_STYLE.get(finding.severity, {"border": "#6b7280", "card_bg": "#f9fafb"})

    st.markdown(
        f'<div style="border-left:4px solid {style["border"]};'
        f'background:{style["card_bg"]};padding:12px 16px;'
        f'border-radius:0 6px 6px 0;margin-bottom:4px;">'
        f'{_severity_badge(finding.severity)}'
        f'&nbsp;&nbsp;<strong>{finding.issue}</strong>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.container():
        col_detail, col_action = st.columns([3, 1])

        with col_detail:
            st.write(f"**Recommendation:** {finding.recommendation}")
            st.caption(
                f"Citation: {_citation_caption(finding.citation)} &nbsp;|&nbsp; "
                f"Confidence: {finding.confidence:.0%}"
            )
            if finding.confidence < CONFIDENCE_REVIEW_THRESHOLD:
                st.caption("⚠️ **Manual Review Recommended** — confidence below 70%")
            with st.expander("📄 View policy detail"):
                _render_citation_detail(finding.citation)

        with col_action:
            decision_key = f"decision_{fid}"
            # reason_key is a plain session_state slot (never a widget key) so
            # Streamlit's widget-cleanup pass will not clear it between reruns.
            reason_key = f"reason_{fid}"
            # text_area_key is the widget's own key — Streamlit may clear it
            # once the override_pending branch is no longer rendered.
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
                        # Persist the reason before rerun so it survives widget
                        # cleanup (Streamlit removes text_area_key from session
                        # state when the widget is no longer rendered).
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
    """Render Save Decision button (or saved confirmation) below a decided finding."""
    if st.session_state.get(saved_key):
        st.caption("✅ Saved to audit log")
        return

    if not reviewer_name.strip():
        st.caption("Enter your name in the sidebar to save.")
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


def _clear_review_state() -> None:
    keys_to_clear = [
        k for k in st.session_state
        if k.startswith(("decision_", "reason_", "saved_", "reason_input_"))
    ]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state.pop("findings", None)
    st.session_state.pop("risk", None)
    st.session_state.pop("reviewed_claim_id", None)


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

    csv_str = repo.export_decisions_csv(
        claim_id=claim_filter.strip() or None,
        reviewer_name=reviewer_filter.strip() or None,
    )
    st.download_button(
        "📥 Export to CSV",
        data=csv_str,
        file_name="audit_decisions.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Denial Prevention Copilot",
        page_icon="🏥",
        layout="wide",
    )

    repo = get_repo()

    # Sidebar — reviewer identity (session-scoped)
    with st.sidebar:
        st.header("Reviewer")
        reviewer_name = st.text_input(
            "Your name",
            key="reviewer_name",
            placeholder="Enter your name to save decisions",
        )
        st.caption("Required to save decisions to the audit log.")

    st.title("Denial Prevention Copilot")
    st.caption("*AI researches, humans decide.*")
    st.divider()

    tab_review, tab_audit = st.tabs(["🔍 Review Claim", "📋 Audit Trail"])

    with tab_review:
        claims = load_claims()
        claim_labels = [f"{c['claim_id']} — {c['description']}" for c in claims]

        selected_label = st.selectbox("Select a synthetic claim", claim_labels)
        selected_idx = claim_labels.index(selected_label)
        claim_dict = claims[selected_idx]

        # Reset review state whenever the selected claim changes
        if st.session_state.get("selected_claim_id") != claim_dict["claim_id"]:
            _clear_review_state()
            st.session_state["selected_claim_id"] = claim_dict["claim_id"]

        # Claim details
        with st.expander("Claim Details", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Claim ID:** {claim_dict['claim_id']}")
                st.write(f"**Payer:** {claim_dict['payer']}")
                st.write(f"**NPI:** {claim_dict['npi']}")
                st.write(f"**Place of Service:** {claim_dict['place_of_service']}")
            with col2:
                st.write(f"**CPT / HCPCS codes:** {', '.join(claim_dict['cpt_codes'])}")
                st.write(f"**ICD-10 diagnoses:** {', '.join(claim_dict['icd10_codes'])}")
                mods = ", ".join(claim_dict.get("modifiers", [])) or "None"
                st.write(f"**Modifiers:** {mods}")

        st.divider()

        if st.button("🔍 Review Claim", type="primary"):
            _clear_review_state()
            claim = load_claim(claim_dict)
            findings = review_claim(claim)
            risk = overall_risk(findings)
            st.session_state["findings"] = findings
            st.session_state["risk"] = risk
            st.session_state["reviewed_claim_id"] = claim_dict["claim_id"]

        # Show results if a review has been run for the currently selected claim
        if (
            "findings" in st.session_state
            and st.session_state.get("reviewed_claim_id") == claim_dict["claim_id"]
        ):
            findings = st.session_state["findings"]
            risk = st.session_state["risk"]

            label, kind = _RISK_CONFIG[risk]
            getattr(st, kind)(label)

            if not findings:
                checks = ["NCCI PTP bundling", "Diagnosis-to-procedure conflict", "Missing modifier 25"]
                st.write("Checks run: " + ", ".join(checks))
            else:
                st.subheader(f"Findings ({len(findings)})")
                for finding in findings:
                    _finding_card(
                        finding,
                        claim_id=claim_dict["claim_id"],
                        reviewer_name=reviewer_name,
                        repo=repo,
                    )

    with tab_audit:
        _render_audit_trail(repo)


if __name__ == "__main__":
    main()
