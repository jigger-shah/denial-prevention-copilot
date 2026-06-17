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
import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from rules.rule_engine import load_claim, review_claim, overall_risk, CHECKS_RUN
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

CLAIMS_FILE = pathlib.Path(__file__).parent.parent / "data" / "synthetic" / "sample_claims.json"
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

_SL_COLS = [2.0, 0.9, 0.9, 0.7, 1.3, 1.3, 1.3, 1.3, 0.7]
_SL_HEADERS = ["CPT / HCPCS", "Mod 1", "Mod 2", "Units", "ICD-10 (1)", "ICD-10 (2)", "ICD-10 (3)", "ICD-10 (4)", ""]


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
# Shared helpers
# ---------------------------------------------------------------------------

def _severity_badge(severity: str) -> str:
    style = _SEVERITY_STYLE.get(severity, {"badge_bg": "#6b7280"})
    return (
        f'<span style="background:{style["badge_bg"]};color:#fff;'
        f'padding:2px 10px;border-radius:4px;font-size:0.72rem;'
        f'font-weight:700;letter-spacing:0.05em;">{severity}</span>'
    )


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


def _render_checks_summary(findings: list) -> None:
    """Always-visible summary of which rule checks ran (and which were skipped)."""
    npi_short_circuited = any(
        f.rule == "npi_invalid" and f.severity == "HIGH" for f in findings
    )
    if npi_short_circuited:
        st.caption(
            "⚡ **NPI short-circuit:** invalid NPI stopped evaluation. "
            "Fix the NPI to run NCCI, MUE, and code-validity checks."
        )
        st.caption("Checks run: " + CHECKS_RUN[0])
    else:
        st.caption("Checks run: " + " · ".join(CHECKS_RUN))


def _clear_review_state() -> None:
    keys_to_clear = [
        k for k in st.session_state
        if k.startswith(("decision_", "reason_", "saved_", "reason_input_"))
    ]
    for k in keys_to_clear:
        del st.session_state[k]
    for key in ("findings", "risk", "reviewed_claim_id", "manual_reviewed", "manual_claim_dict"):
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
# Manual mode callbacks (module-level so Streamlit can serialize them)
# ---------------------------------------------------------------------------

def _on_payer_name_change() -> None:
    name = st.session_state.get("manual_payer_name", "")
    st.session_state["manual_payer_id"] = get_payer_id(name)


def _clear_manual_form() -> None:
    keys_to_clear = [k for k in st.session_state if k.startswith(("manual_", "sl_"))]
    for k in keys_to_clear:
        del st.session_state[k]
    _clear_review_state()


def _load_worked_example() -> None:
    _clear_manual_form()
    ex = WORKED_EXAMPLE
    st.session_state["manual_claim_id"] = ex["claim_id"]
    st.session_state["manual_payer_name"] = ex["payer_name"]
    st.session_state["manual_payer_id"] = get_payer_id(ex["payer_name"])
    st.session_state["manual_specialty"] = ex["provider_specialty"]
    st.session_state["manual_npi"] = ex["npi"]
    st.session_state["manual_note_text"] = ex["note_text"]
    row_ids = list(range(len(ex["service_lines"])))
    st.session_state["manual_active_rows"] = row_ids
    st.session_state["manual_next_row_id"] = len(ex["service_lines"])
    for row_id, line in zip(row_ids, ex["service_lines"]):
        for field in ("cpt", "mod1", "mod2", "icd10_1", "icd10_2", "icd10_3", "icd10_4"):
            st.session_state[f"sl_{row_id}_{field}"] = line[field]
        st.session_state[f"sl_{row_id}_units"] = line.get("units", 1)


# ---------------------------------------------------------------------------
# Manual Claim Entry UI
# ---------------------------------------------------------------------------

def _render_manual_mode(reviewer_name: str, repo: AuditRepository) -> None:
    # Init service-line tracking if not present (also re-initializes after Clear Form)
    if "manual_active_rows" not in st.session_state:
        st.session_state["manual_active_rows"] = [0]
        st.session_state["manual_next_row_id"] = 1

    # ---- Claim Header ----
    st.subheader("Claim Header")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.text_input(
            "Claim ID *",
            key="manual_claim_id",
            placeholder="CLM-MANUAL-001",
        )
    with col2:
        payer_options = [_PAYER_PLACEHOLDER] + list(PAYER_ID_MAP.keys())
        st.selectbox(
            "Payer *",
            options=payer_options,
            key="manual_payer_name",
            on_change=_on_payer_name_change,
        )
    with col3:
        st.text_input(
            "Payer ID",
            key="manual_payer_id",
            placeholder="Auto-populated from payer selection",
        )

    col4, col5 = st.columns(2)
    with col4:
        st.text_input(
            "Provider NPI (optional)",
            key="manual_npi",
            placeholder="10-digit NPI number",
            max_chars=10,
            help="Format validated here. Luhn check-digit and NPPES registry lookup run at review time.",
        )
    with col5:
        st.text_input(
            "Provider Specialty (optional)",
            key="manual_specialty",
            placeholder="e.g. Internal Medicine",
        )

    st.text_area(
        "Clinical Notes (optional)",
        key="manual_note_text",
        placeholder="Paste de-identified clinical documentation here…",
        height=80,
    )
    st.caption("⚠️ Do not enter PHI. Synthetic or de-identified notes only.")

    st.divider()

    # ---- Service-Line Coding Grid ----
    st.subheader("Service Lines")

    hdr_cols = st.columns(_SL_COLS)
    for col, hdr in zip(hdr_cols, _SL_HEADERS):
        if hdr:
            col.markdown(f"**{hdr}**")

    active_rows: list[int] = st.session_state["manual_active_rows"]
    rows_to_remove: list[int] = []

    for row_id in active_rows:
        cols = st.columns(_SL_COLS)
        cols[0].text_input("CPT", key=f"sl_{row_id}_cpt", label_visibility="collapsed", placeholder="99213")
        cols[1].text_input("Mod1", key=f"sl_{row_id}_mod1", label_visibility="collapsed", placeholder="25")
        cols[2].text_input("Mod2", key=f"sl_{row_id}_mod2", label_visibility="collapsed", placeholder="")
        cols[3].number_input("Units", key=f"sl_{row_id}_units", min_value=1, max_value=999, value=1, label_visibility="collapsed")
        cols[4].text_input("ICD1", key=f"sl_{row_id}_icd10_1", label_visibility="collapsed", placeholder="Z00.00")
        cols[5].text_input("ICD2", key=f"sl_{row_id}_icd10_2", label_visibility="collapsed", placeholder="")
        cols[6].text_input("ICD3", key=f"sl_{row_id}_icd10_3", label_visibility="collapsed", placeholder="")
        cols[7].text_input("ICD4", key=f"sl_{row_id}_icd10_4", label_visibility="collapsed", placeholder="")
        if len(active_rows) > 1:
            if cols[8].button("✕", key=f"sl_rm_{row_id}", help="Remove this service line"):
                rows_to_remove.append(row_id)

    if rows_to_remove:
        st.session_state["manual_active_rows"] = [r for r in active_rows if r not in rows_to_remove]
        _clear_review_state()

    # Add / Clear / Load buttons
    btn_add, btn_clear, btn_example, _ = st.columns([1.5, 1.2, 1.8, 4])
    if btn_add.button("➕ Add Service Line", key="manual_add_sl"):
        next_id = st.session_state["manual_next_row_id"]
        st.session_state["manual_active_rows"].append(next_id)
        st.session_state["manual_next_row_id"] = next_id + 1

    btn_clear.button("🗑 Clear Form", key="manual_clear_btn", on_click=_clear_manual_form)
    btn_example.button("📋 Load Worked Example", key="manual_example_btn", on_click=_load_worked_example)

    st.divider()

    # ---- Review button ----
    if st.button("🔍 Review Claim", type="primary", key="manual_review_btn"):
        header = {
            "claim_id": st.session_state.get("manual_claim_id", "").strip(),
            "payer_name": st.session_state.get("manual_payer_name", ""),
            "payer_id": st.session_state.get("manual_payer_id", "").strip(),
            "npi": st.session_state.get("manual_npi", "").strip(),
            "provider_specialty": st.session_state.get("manual_specialty", "").strip(),
            "note_text": st.session_state.get("manual_note_text", "").strip(),
        }

        lines = [
            {
                "cpt": st.session_state.get(f"sl_{row_id}_cpt", ""),
                "mod1": st.session_state.get(f"sl_{row_id}_mod1", ""),
                "mod2": st.session_state.get(f"sl_{row_id}_mod2", ""),
                "units": st.session_state.get(f"sl_{row_id}_units", 1),
                "icd10_1": st.session_state.get(f"sl_{row_id}_icd10_1", ""),
                "icd10_2": st.session_state.get(f"sl_{row_id}_icd10_2", ""),
                "icd10_3": st.session_state.get(f"sl_{row_id}_icd10_3", ""),
                "icd10_4": st.session_state.get(f"sl_{row_id}_icd10_4", ""),
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
            for err in errors:
                st.error(err)
        else:
            _clear_review_state()
            claim_dict = build_manual_claim(header, lines)
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


# ---------------------------------------------------------------------------
# Sample Claim UI (existing mode, unchanged)
# ---------------------------------------------------------------------------

def _render_sample_mode(reviewer_name: str, repo: AuditRepository) -> None:
    claims = load_claims()
    claim_labels = [f"{c['claim_id']} — {c['description']}" for c in claims]

    selected_label = st.selectbox("Select a synthetic claim", claim_labels)
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

    if st.button("🔍 Review Claim", type="primary", key="sample_review_btn"):
        _clear_review_state()
        claim = load_claim(claim_dict)
        findings = review_claim(claim)
        risk = overall_risk(findings)
        st.session_state["findings"] = findings
        st.session_state["risk"] = risk
        st.session_state["reviewed_claim_id"] = claim_dict["claim_id"]

    if (
        "findings" in st.session_state
        and st.session_state.get("reviewed_claim_id") == claim_dict["claim_id"]
    ):
        findings = st.session_state["findings"]
        risk = st.session_state["risk"]

        label, kind = _RISK_CONFIG[risk]
        getattr(st, kind)(label)
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

    with st.sidebar:
        st.header("Reviewer")
        reviewer_name = st.text_input(
            "Your name",
            key="reviewer_name",
            placeholder="Enter your name to save decisions",
        )
        st.caption("Required to save decisions to the audit log.")

    st.title("Denial Prevention Copilot")
    st.caption("AI does the research. Humans make the call.")
    st.divider()

    tab_review, tab_audit = st.tabs(["🔍 Review Claim", "📋 Audit Trail"])

    with tab_review:
        mode = st.radio(
            "Claim entry mode",
            options=["Sample Claim", "Manual Claim Entry"],
            horizontal=True,
            key="claim_mode",
            label_visibility="collapsed",
        )

        # Clear review state when mode switches
        prev_mode = st.session_state.get("_claim_mode_prev")
        if prev_mode is not None and prev_mode != mode:
            _clear_review_state()
        st.session_state["_claim_mode_prev"] = mode

        st.divider()

        if mode == "Sample Claim":
            _render_sample_mode(reviewer_name, repo)
        else:
            _render_manual_mode(reviewer_name, repo)

    with tab_audit:
        _render_audit_trail(repo)


if __name__ == "__main__":
    main()
