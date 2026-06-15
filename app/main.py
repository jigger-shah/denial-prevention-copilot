"""
Streamlit entry point for the Denial Prevention Copilot.

Responsibilities:
  - Load synthetic claims from data/synthetic/sample_claims.json.
  - Let the user select a claim and display its details.
  - On "Review Claim", call rules.rule_engine — no business logic here.
  - Render findings with color-coded severity badges.
  - Capture per-finding Accept / Override decisions in session state.

All rule evaluation lives in rules/rule_engine.py.
"""

import json
import pathlib
import sys

# Ensure the project root is on sys.path so `rules` is importable when
# Streamlit is launched with `streamlit run app/main.py` (Streamlit adds
# the script's directory, not the repo root, to sys.path by default).
_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from rules.rule_engine import load_claim, review_claim, overall_risk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAIMS_FILE = pathlib.Path(__file__).parent.parent / "data" / "synthetic" / "sample_claims.json"

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
# Helpers
# ---------------------------------------------------------------------------

@st.cache_data
def load_claims() -> list[dict]:
    with open(CLAIMS_FILE) as f:
        return json.load(f)


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


def _finding_card(finding) -> None:
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
            if finding.citation.excerpt:
                with st.expander("View source excerpt"):
                    st.markdown(
                        f'<div style="font-size:0.85rem;color:#374151;'
                        f'font-style:italic;padding:4px 0;">'
                        f'"{finding.citation.excerpt}"</div>',
                        unsafe_allow_html=True,
                    )

        with col_action:
            decision_key = f"decision_{fid}"
            reason_key = f"reason_{fid}"

            decision = st.session_state.get(decision_key)

            if decision is None:
                btn_col1, btn_col2 = st.columns(2)
                if btn_col1.button("✓ Accept", key=f"accept_{fid}", use_container_width=True):
                    st.session_state[decision_key] = "accepted"
                    st.rerun()
                if btn_col2.button("✗ Override", key=f"override_{fid}", use_container_width=True):
                    st.session_state[decision_key] = "override_pending"
                    st.rerun()

            elif decision == "override_pending":
                reason = st.text_area(
                    "Override reason (required)",
                    key=reason_key,
                    height=80,
                    placeholder="Explain why you are overriding this finding…",
                )
                if st.button("Confirm", key=f"confirm_{fid}"):
                    if reason.strip():
                        st.session_state[decision_key] = "overridden"
                        st.rerun()
                    else:
                        st.warning("Please enter a reason before confirming.")

            elif decision == "accepted":
                st.success("✓ Accepted")

            elif decision == "overridden":
                stored_reason = st.session_state.get(reason_key, "")
                st.warning("⚠ Overridden")
                if stored_reason:
                    st.caption(f"Reason: {stored_reason}")

    st.divider()


def _clear_review_state() -> None:
    keys_to_clear = [k for k in st.session_state if k.startswith(("decision_", "reason_", "findings_", "risk_"))]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state.pop("findings", None)
    st.session_state.pop("risk", None)
    st.session_state.pop("reviewed_claim_id", None)


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Denial Prevention Copilot",
        page_icon="🏥",
        layout="wide",
    )

    st.title("Denial Prevention Copilot")
    st.caption("*AI researches, humans decide.*")
    st.divider()

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
                _finding_card(finding)


if __name__ == "__main__":
    main()
