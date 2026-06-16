# Repository Status Report
## Denial Prevention Copilot — Comprehensive Project Assessment

**Date:** June 2026
**Branch:** main
**Last commit:** Sprint 4 — Manual Claim Intake with Service-Line Coding Grid
**Test suite:** 83 tests, all passing, < 0.1s runtime

---

## Executive Summary

### Current Maturity Level

**Early Infrastructure Complete. AI Layer Not Started.**

The Denial Prevention Copilot is a pre-submission healthcare claim review copilot built on a sound engineering foundation. Three full sprints have been completed. The governance architecture, data model, deterministic rule layer, and policy reference layer are all production-quality. The LLM agent layer — the product's primary value proposition — has not yet been implemented.

### Overall MVP Completion

| Layer | Complete | Notes |
|---|---|---|
| Data model (ClaimIn, Citation, Finding, AuditDecision) | ✅ 100% | All models complete and audit-ready |
| Deterministic rule layer | 🟡 ~15% | 3 rules of ~250,000+ NCCI pairs + full MUE + NPI |
| Policy intelligence layer | 🟡 ~10% | 5 curated references; real CMS ingestion not built |
| Human review workflow | ✅ 100% | Accept / Override / Save fully wired |
| Audit persistence | ✅ 100% | Append-only SQLite, governance-enforced |
| LLM agent layer | ❌ 0% | All agents are docstring stubs |
| RAG retrieval pipeline | ❌ 0% | ChromaDB, ingest, chunking all stubs |
| Claim intake form | 🟡 ~60% | Manual entry + service-line grid live; CSV upload and NPI Luhn check not yet built |
| Evaluation framework | ❌ 0% | No golden set, no precision/recall measurement |

**Estimated overall MVP completion: ~35%**

The 30% reflects the foundation being complete and correct, while the primary user-facing differentiator (AI-powered medical necessity findings from retrieved CMS policy) is entirely absent.

### Key Strengths

1. **Governance-first architecture.** Audit logging, citation requirement, and human decision workflow were built before any AI — the right order for a healthcare product. This is a genuine product judgment call, not an accident, and it reads that way.

2. **Data model designed for the full system.** `Citation`, `Finding`, `AuditDecision`, and `finding_id` are already structured to support agent findings, RAG citations, and compliance audit without schema changes. Every agent can slot in without touching the existing contract.

3. **Evidence-backed citations.** Sprint 3 replaced hollow synthetic strings with structured policy references that carry real CMS source URLs, section citations, effective dates, and policy-level excerpts. The app reads as evidence-backed rather than toy-like.

4. **Append-only audit log with governance enforcement.** `AuditRepository.save_decision()` rejects any finding without a `finding_id`, any finding without a complete citation, and any override without a reason — at the repository layer, not the UI layer. This is architecturally correct and uncommon in portfolio projects.

5. **55 tests with zero mocks.** The test suite uses inline data, tmp_path databases, and the real JSON policy file. No mocked modules, no patched functions. Every passing test is a real execution of real code.

6. **Replacement seams are explicit.** Every hardcoded data source has a clearly documented replacement path with the same public interface. `_load_ptp_edits()`, `_load_policy_references()`, and the rule engine's checker list are all designed to be swapped without touching callers.

### Biggest Remaining Gaps

1. **No LLM agent layer.** The product's core thesis — AI researches, humans decide — cannot be demonstrated. Every finding today comes from a hardcoded rule.
2. **No RAG retrieval pipeline.** The Coverage Validation Agent cannot be built without indexed LCD/NCD text. This is a hard dependency for the primary AI feature.
3. **Limited claim intake.** Manual entry is live (service-line grid, payer mapping, NPI format validation); CSV upload and Luhn check-digit NPI validation are not yet built.
4. **Only 1 of ~250,000 NCCI edit pairs.** The NCCI bundling check is functionally a one-rule demo.
5. **No evaluation infrastructure.** Cannot measure or demonstrate finding precision/recall against the PRD targets.

---

## Current Architecture

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Streamlit UI  (app/main.py)                                                  │
│                                                                               │
│  Sidebar: Reviewer Name (required to save)                                    │
│  ┌───────────────────────────────────┐  ┌──────────────────────────────────┐ │
│  │  🔍 Review Claim tab              │  │  📋 Audit Trail tab              │ │
│  │                                   │  │                                  │ │
│  │  ◉ Sample Claim  ○ Manual Entry   │  │  Filter: claim_id / reviewer     │ │
│  │  ─────────────────────────────    │  │  Decision table (DataFrame)      │ │
│  │  [Sample] Claim Selector (5)      │  │  [📥 Export to CSV]              │ │
│  │           Claim Details expander  │  │                                  │ │
│  │  [Manual] Claim Header fields     │  │                                  │ │
│  │           Service-Line Grid       │  │                                  │ │
│  │           Add/Clear/Load Example  │  │                                  │ │
│  │  [🔍 Review Claim] (primary btn)  │  │                                  │ │
│  │                                   │  │                                  │ │
│  │  Risk Banner (HIGH/MED/LOW/CLEAN) │  └──────────────────────────────────┘ │
│  │                                   │                                        │
│  │  Finding Card (per finding):      │                                        │
│  │   ● Severity badge + issue text   │                                        │
│  │   ● Recommendation                │                                        │
│  │   ● Citation caption (one line)   │                                        │
│  │   ● 📄 View policy detail ▾       │  ← Sprint 3: title, URL, section,     │
│  │      source / doc_id / section    │    effective_date, excerpt, notes      │
│  │      edition / effective_date     │                                        │
│  │      title / source_url           │                                        │
│  │      policy excerpt               │                                        │
│  │      notes                        │                                        │
│  │   ● [✓ Accept] [✗ Override]       │                                        │
│  │     (Override → reason text area) │                                        │
│  │   ● [💾 Save Decision]            │                                        │
│  └───────────────────────────────────┘                                        │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │ calls
                               ▼
┌──────────────────────────────────────────────┐
│  rules/rule_engine.py   IMPLEMENTED          │
│  load_claim(dict) → ClaimIn                  │
│  review_claim(claim) → list[Finding]         │
│    ├── ncci.check_ncci_pairs()               │
│    ├── code_validity.check_code_validity()   │
│    └── _make_finding_id() [SHA-256]          │
│  overall_risk(findings) → str                │
└──────────┬───────────────────────────────────┘
           │ calls
           ├─────────────────────────────────────────────────┐
           ▼                                                 ▼
┌────────────────────────────┐       ┌───────────────────────────────────┐
│  rules/ncci.py             │       │  rules/code_validity.py           │
│  IMPLEMENTED (partial)     │       │  IMPLEMENTED (partial)            │
│  1 PTP edit pair (of ~250k)│       │  1 dx-procedure conflict rule     │
│  Citation → policy_repo    │       │  1 modifier rule                  │
│                            │       │  Citation → policy_repo           │
└────────────────────────────┘       └───────────────────────────────────┘

           │ (Citations enriched by)
           ▼
┌──────────────────────────────────────────────┐
│  retrieval/policy_repository.py  IMPLEMENTED │
│  load_policy_references()  → JSON cache       │
│  find_policy_by_document_id(doc_id)           │
│  find_policies_by_codes(cpt, icd10, mods)     │
│  get_citation_detail(citation) → dict         │
│                                               │
│  Backed by:                                   │
│  data/reference/policy_examples.json          │
│  5 curated policy references                  │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│  db/audit_repository.py   IMPLEMENTED        │
│  AuditDecision (19 fields + id/timestamp)    │
│  AuditRepository:                            │
│    initialize_database() + migration         │
│    save_decision() → governance-enforced     │
│    get_decisions() → filtered SELECT         │
│    export_decisions_csv() → CSV string       │
│  audit_decisions table (19 columns)          │
│  db/audit.db (gitignored, created on run)    │
└──────────────────────────────────────────────┘

        ┌──────── STUBS — docstring only, no implementation ────────┐
        │  rules/mue.py              MUE table lookup               │
        │  rules/npi.py              NPPES live API + Luhn          │
        │  agents/orchestrator.py    parallel dispatch              │
        │  agents/coding_validation.py                              │
        │  agents/coverage_validation.py   ← RAG + Claude API      │
        │  agents/documentation_review.py  ← LLM clinical notes    │
        │  agents/denial_prevention.py     ← synthesis             │
        │  retrieval/ingest.py             ← CMS Coverage API      │
        │  retrieval/chunking.py           ← section-aware split   │
        │  retrieval/vector_store.py       ← ChromaDB              │
        │  app/components/claim_form.py    ← component stub        │
        │  app/components/findings_panel.py                        │
        │  app/components/audit_view.py                            │
        └───────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Status | Responsibility |
|---|---|---|
| `rules/rule_engine.py` | ✅ Implemented | Orchestrates rule checks, stamps `finding_id` via SHA-256, sorts findings |
| `rules/models.py` | ✅ Implemented | `ClaimIn`, `Citation`, `Finding` dataclasses — shared contract across all layers |
| `rules/ncci.py` | 🟡 Partial | NCCI PTP bundling check — 1 hardcoded edit pair, full CSV interface stubbed |
| `rules/code_validity.py` | 🟡 Partial | Dx-procedure conflict and modifier checks — 2 hardcoded rules |
| `rules/mue.py` | ❌ Stub | MUE unit limit checks — not implemented |
| `rules/npi.py` | ❌ Stub | NPPES NPI validation + Luhn — not implemented |
| `retrieval/policy_repository.py` | ✅ Implemented | JSON-backed policy lookup; future replacement with ChromaDB |
| `retrieval/ingest.py` | ❌ Stub | CMS Coverage API fetcher — not implemented |
| `retrieval/chunking.py` | ❌ Stub | Section-aware LCD/NCD splitter — not implemented |
| `retrieval/vector_store.py` | ❌ Stub | ChromaDB index/query — not implemented |
| `agents/orchestrator.py` | ❌ Stub | Parallel agent dispatch — not implemented |
| `agents/coverage_validation.py` | ❌ Stub | RAG + LLM medical necessity — not implemented |
| `agents/documentation_review.py` | ❌ Stub | LLM clinical note analysis — not implemented |
| `agents/denial_prevention.py` | ❌ Stub | Deterministic synthesis → `RiskAssessment` — not implemented |
| `db/audit_repository.py` | ✅ Implemented | Append-only audit persistence, governance enforcement |
| `app/main.py` | ✅ Implemented | Streamlit UI — Sample + Manual modes, all current features |
| `app/claim_intake.py` | ✅ Implemented | `build_manual_claim()`, payer mapping, NPI format validation, normalization |
| `app/components/` | ❌ Stub | UI component modules — not implemented |

### Data Flow

```
[Sample mode] User selects claim from dropdown
    → load_claim(dict) → ClaimIn

[Manual mode] User fills claim header + service-line grid → [🔍 Review Claim]
    → build_manual_claim(header, service_lines) → claim_dict
        → normalize_code() on all CPT / ICD-10 / modifier fields
        → deduplicate across service lines
        → payer_name → payer_id via PAYER_ID_MAP
    → load_claim(claim_dict) → ClaimIn
        (accepts "payer" or "payer_name" key; npi / place_of_service optional)

Both modes:
    → review_claim(ClaimIn)
        → ncci.check_ncci_pairs() → list[Finding] (Citation → NCCI_PTP doc_id)
        → code_validity.check_code_validity() → list[Finding] (Citation → ICD10/NCCI_MOD doc_ids)
        → sort by severity (HIGH → MEDIUM → LOW)
        → stamp finding_id = SHA-256(claim_id:rule:issue)[:12]
    → overall_risk(findings) → "HIGH" | "MEDIUM" | "LOW" | "CLEAN"
    → app/main.py renders:
        → _finding_card(finding)
            → _citation_caption(citation) → one-line string
            → "📄 View policy detail"
                → get_citation_detail(citation)
                    → find_policy_by_document_id(doc_id)
                        → scan policy_examples.json
                    → render: title, source_url, section, edition, effective_date, excerpt, notes
```

### Audit Flow

```
User clicks [💾 Save Decision]
    → AuditDecision(claim_id, finding_id, source, severity, issue, recommendation,
                    citation_source, citation_doc_id, citation_section, citation_edition,
                    citation_effective_date, confidence, user_decision, override_reason,
                    reviewer_name, model_version, prompt_version)
    → AuditRepository.save_decision(decision)
        → validate: finding_id not empty
        → validate: citation_source and citation_doc_id not empty
        → validate: if overridden → override_reason not empty
        → INSERT INTO audit_decisions (...) VALUES (...)
        → return row id
    → st.session_state[saved_key] = True
    → st.rerun() → "✅ Saved to audit log"
```

### Citation Flow

```
Rule module (ncci.py / code_validity.py)
    → Citation(
          source="NCCI PTP",
          doc_id="NCCI_PTP_80048_80053_SAMPLE",
          section="Physician/Practitioner PTP Edit Table, Column 1 / Column 2",
          edition="NCCI Policy Manual for Medicare Services (sample reference)",
          effective_date="2000-01-01",
          excerpt="CPT code 80048 is a component of CPT code 80053..."
      )
    → Finding.citation = Citation

UI (_render_citation_detail)
    → get_citation_detail(citation)
        → find_policy_by_document_id("NCCI_PTP_80048_80053_SAMPLE")
            → policy_examples.json lookup
        → returns {title, source_url, notes, ...}
    → renders: source / doc_id / section / edition / effective_date / title / URL / excerpt / notes

Audit log (save_decision)
    → citation_source = "NCCI PTP"
    → citation_doc_id = "NCCI_PTP_80048_80053_SAMPLE"
    → citation_section = "Physician/Practitioner PTP Edit Table..."
    → citation_edition = "NCCI Policy Manual... (sample reference)"
    → citation_effective_date = "2000-01-01"
```

---

## Implemented Features

### 1. Deterministic Rule Engine

**Status:** ✅ Implemented (partial data coverage)
**Files:** `rules/rule_engine.py`, `rules/models.py`, `rules/ncci.py`, `rules/code_validity.py`

The rule engine is the synchronous first layer. It runs all registered rule modules, aggregates their findings, sorts by severity, and stamps a stable `finding_id` on each finding. Adding a new rule module requires one import and one function call — the interface is complete and extensible.

| Check | Status | Coverage |
|---|---|---|
| NCCI PTP bundling (80048/80053) | ✅ | 1 of ~250,000 edit pairs |
| Dx-procedure conflict (Z00.00 vs problem E/M) | ✅ | 1 of thousands of conflict rules |
| Missing modifier 25 in preventive context | ✅ | 1 of many modifier rules |
| MUE unit limit violations | ❌ | Stub — not implemented |
| NPI validity / deactivation | ❌ | Stub — not implemented |
| HCPCS Level II validity | ❌ | Not implemented |

### 2. Policy Intelligence Layer

**Status:** ✅ Implemented (curated dataset, not live CMS)
**Files:** `retrieval/policy_repository.py`, `data/reference/policy_examples.json`

Five curated public-policy-style references cover the three active rule findings plus two illustrative examples (LCD venipuncture, MUE panel limits). Each entry carries `document_id`, `source_type`, `title`, `section`, `effective_date`, `edition`, `source_url`, `excerpt`, `applies_to_codes`, and `notes`. The repository service is designed so that `_load_policy_references()` is the only function that touches the JSON file — replacing it with a ChromaDB query is a one-function swap.

### 3. Structured Citations

**Status:** ✅ Implemented
**Files:** `rules/models.py`, `rules/ncci.py`, `rules/code_validity.py`

Every `Finding` carries a `Citation` dataclass with six fields: `source`, `doc_id`, `section`, `edition`, `effective_date`, `excerpt`. These fields map field-for-field to the `audit_decisions` table columns. No finding can reach the audit log without a complete, structured citation — this is enforced at the repository layer, not just the UI.

### 4. Human Review Workflow

**Status:** ✅ Implemented
**Files:** `app/main.py`

The reviewer workflow is complete: select claim → review → see findings → accept or override each finding → save with reviewer name. Override decisions require a non-empty reason entered in a text area before the save button is enabled. The "Manual Review Recommended" badge triggers for confidence below 70%. Session state is keyed by `finding_id` (not list position), so findings can be reordered without mixing up decisions.

### 5. Audit Trail

**Status:** ✅ Implemented
**Files:** `db/audit_repository.py`, `app/main.py`

The Audit Trail tab shows all saved decisions, filterable by `claim_id` and `reviewer_name`. Displayed columns include `timestamp`, `finding_id`, `severity`, `user_decision`, `reviewer_name`, `citation_source`, `citation_doc_id`, `citation_section`, and `citation_effective_date`. The table is rendered as a Pandas DataFrame via `st.dataframe`.

### 6. SQLite Persistence

**Status:** ✅ Implemented
**Files:** `db/audit_repository.py`

The `audit_decisions` table is append-only (INSERT only, no UPDATE or DELETE). The `initialize_database()` method creates the table on first run and applies a backward-compatible `ALTER TABLE` migration for `citation_effective_date` on databases created before Sprint 3. `AuditRepository` is the only path to the database — `app/main.py` never imports `sqlite3` directly.

Governance rules enforced by `save_decision()`:
- `finding_id` must be non-empty
- `citation_source` and `citation_doc_id` must be non-empty
- `override_reason` must be non-empty when `user_decision == "overridden"`

### 7. CSV Export

**Status:** ✅ Implemented
**Files:** `db/audit_repository.py`, `app/main.py`

`export_decisions_csv()` returns a CSV string with a header row followed by all matching rows. The `st.download_button` in the Audit Trail tab triggers a file download with the current filter applied. The export includes all 19 columns of `audit_decisions`.

### 8. Tests

**Status:** ✅ 55 tests, all passing
**Files:** `tests/test_rule_engine.py`, `tests/test_audit.py`, `tests/test_policy_repository.py`

| File | Tests | Coverage |
|---|---|---|
| `test_rule_engine.py` | 20 | NCCI bundling, dx conflict, modifier, risk scoring, finding_id stability, Citation structure, source field |
| `test_audit.py` | 15 | Persistence, governance validation, filtering, CSV export, override/accept behavior |
| `test_policy_repository.py` | 20 | JSON loading, document_id lookup, code-based lookup, citation resolution per rule, audit migration |

Zero mocks. No network calls. All database tests use `tmp_path` isolation.

### 9. Documentation

**Status:** ✅ Comprehensive suite
**Files:** `docs/` (6 documents)

| Document | Purpose |
|---|---|
| `Architecture_Decisions.md` | 9 ADRs covering all major decisions (including ADR-009: local policy JSON) |
| `Technical_Debt_Register.md` | 25 items (8 resolved, 17 open) with location, impact, and remediation plan |
| `Roadmap.md` | 11 phases (5 complete, 6 future) with deliverables, dependencies, and success criteria |
| `Demo_Script.md` | 30s/2min/5min scripts plus Q&A for PM, AI PM, and Healthcare AI audiences |
| `Pre_Audit_Architecture_Review.md` | Permanent record of model refactor rationale (Citation, finding_id, source) |
| `Repository_Status_Report.md` | This document |

---

## PRD Traceability Matrix

| PRD Requirement | Section | Status | Evidence |
|---|---|---|---|
| Pre-submission claim review before adjudication | §1 Vision | 🟡 Partial | Rule-based review works; agent-based review not wired |
| Deterministic validation: NCCI PTP pairs | §6 P0 | 🟡 Partial | 1 of ~250,000 edit pairs implemented |
| Deterministic validation: MUE limits | §6 P0 | ❌ Not Started | `rules/mue.py` is a stub |
| Deterministic validation: NPI Registry | §6 P0 | ❌ Not Started | `rules/npi.py` is a stub |
| Code validity: ICD-10-CM | §6 P0 | 🟡 Partial | 1 dx-procedure conflict rule; no reference file |
| Code validity: HCPCS Level II | §6 P0 | ❌ Not Started | Not implemented |
| Denial risk severity (HIGH/MEDIUM/LOW) | §6 P0 | ✅ Complete | Enforced in `Finding.severity` Literal type |
| Recommended fix per finding | §6 P0 | ✅ Complete | `Finding.recommendation` on every finding |
| Citation per finding | §6 P0 | ✅ Complete | `Citation` dataclass, `AuditRepository` governance |
| Confidence score per finding | §6 P0 | ✅ Complete | `Finding.confidence` (0.0–1.0), displayed in UI |
| Accept / override workflow | §6 P0 | ✅ Complete | Full workflow with reason capture |
| Override requires documented reason | §6 P0 | ✅ Complete | Enforced in `AuditRepository.save_decision()` |
| Named specialist (reviewer) | §6 P0 | ✅ Complete | Sidebar input, required for save |
| Audit log: inputs, findings, decisions, timestamps | §6 P0 | ✅ Complete | 19-column `audit_decisions` table |
| Audit log: append-only (no modification) | §12 | ✅ Complete | INSERT only; no UPDATE or DELETE in codebase |
| Manual claim intake form | §6 P0 | ❌ Not Started | JSON selector only; `claim_form.py` is a stub |
| CSV batch upload | §6 P1 | ❌ Not Started | Single claim only |
| Coverage validation via LCD/NCD (RAG) | §6 P0 | ❌ Not Started | `coverage_validation.py` is a stub |
| Medical necessity reasoning (LLM) | §6 P0 | ❌ Not Started | No Claude API calls anywhere |
| Documentation review agent | §6 P1 | ❌ Not Started | `documentation_review.py` is a stub |
| Parallel agent dispatch | §9 | ❌ Not Started | `orchestrator.py` is a stub |
| Denial Prevention synthesis + RiskAssessment | §9 | ❌ Not Started | `denial_prevention.py` is a stub |
| Low-confidence escalation flag | §6 P0 | ✅ Complete | "Manual Review Recommended" badge < 70% |
| Exportable audit log (CSV) | §7 Story 4 | ✅ Complete | `export_decisions_csv()` + download button |
| Source excerpt in citation | §7 Story 2 | ✅ Complete | `📄 View policy detail` expander with excerpt |
| Clean claim explicitly marked | §7 Story 1 | ✅ Complete | "CLEAN — no denial risks identified" |
| Checks run listed for clean claim | §7 Story 1 | ✅ Complete | Shown below CLEAN banner |
| Finding precision ≥ 90% on golden set | §14 | ❌ Not Started | No golden set; `pytest -m golden` not built |
| Finding recall ≥ 85% on golden set | §14 | ❌ Not Started | Same |
| Review time ≤ 2 minutes | §14 | 🟡 Partial | UI is instant; agent latency not yet measured |
| PHI protection — synthetic data only | §11 | ✅ Complete | No PHI anywhere in codebase or data files |
| No autonomous action — human decides | §5 P1 | ✅ Complete | Every finding requires explicit accept/override |

**Summary: 15 Complete · 5 Partial · 14 Not Started**

The 15 complete requirements are primarily governance, data model, and workflow requirements. The 14 not-started items are primarily the AI and data-pipeline requirements — the product's core value proposition.

---

## Remaining Gaps

### Gap 1: Manual Claim Intake Form — MEDIUM priority

The UI reads from `data/synthetic/sample_claims.json`. There is no way to enter or upload a claim. Every demo works off the same 5 fixed claims.

**Impact:** A live demo audience sees a pre-selected claim, not a claim being entered. The product cannot be used for any real claim review scenario.
**Files:** `app/components/claim_form.py` (stub), `app/main.py`
**Sprint:** Phase 3

### Gap 2: Real NCCI PTP Ingestion — HIGH priority

Only 1 of ~250,000+ NCCI PTP edit pairs is implemented. Claims that don't include 80053 and 80048 together will never trigger an NCCI finding, regardless of what codes are billed.

**Impact:** The NCCI check is functionally a one-pair demo. Presenting it as "NCCI validation" is misleading.
**Files:** `rules/ncci.py:_load_ptp_edits()`
**Sprint:** Phase 3

### Gap 3: MUE Validation — HIGH priority

The MUE module is a stub. Unit-of-service violations are one of the most common denial reasons for labs, surgical codes, and DME. Every claim in the demo could be billing excessive units with no detection.

**Files:** `rules/mue.py`
**Sprint:** Phase 3

### Gap 4: NPI Validation — HIGH priority

The NPI module is a stub. A deactivated NPI is a hard denial at all payers. The synthetic NPIs in sample_claims.json likely fail Luhn validation. The orchestrator's planned short-circuit behavior (NPI failure skips agents) cannot be demonstrated.

**Files:** `rules/npi.py`
**Sprint:** Phase 3

### Gap 5: LCD/NCD Retrieval Pipeline — HIGH priority (blocks agents)

No LCD or NCD documents have been fetched from the CMS Coverage API or indexed in ChromaDB. This is a hard dependency for the Coverage Validation Agent — without retrieved text, the agent cannot produce cited findings.

**Files:** `retrieval/ingest.py`, `retrieval/chunking.py`, `retrieval/vector_store.py`
**Sprint:** Phase 4

### Gap 6: Coverage Validation Agent — CRITICAL (core value proposition)

The primary differentiator of this product — AI-powered medical necessity review against retrieved CMS coverage policy — is entirely absent. Every finding today comes from a hardcoded rule.

**Files:** `agents/coverage_validation.py`
**Sprint:** Phase 5

### Gap 7: Documentation Review Agent — MEDIUM priority

Clinical note analysis for E/M level support and diagnosis specificity is not implemented. No synthetic notes are attached to sample claims.

**Files:** `agents/documentation_review.py`
**Sprint:** Phase 6

### Gap 8: Orchestrator + Denial Prevention Agent — HIGH priority

Without the orchestrator, agents cannot be dispatched in parallel. Without the Denial Prevention Agent, there is no `RiskAssessment` synthesis. The four-agent architecture in PRD §9 is entirely unimplemented.

**Files:** `agents/orchestrator.py`, `agents/denial_prevention.py`
**Sprint:** Phase 7

### Gap 9: Evaluation Framework — MEDIUM priority

No golden set exists. `pytest -m golden` is documented but produces zero tests. Finding precision and recall — the primary quality metrics from PRD §14 — cannot be measured or demonstrated.

**Files:** `tests/test_golden.py` (missing), `data/synthetic/golden_claims.json` (missing)
**Sprint:** Phase 8

### Gap 10: Deployment Readiness — LOW priority

The app cannot be deployed to Streamlit Cloud as-is: no `st.secrets` integration, `db/audit.db` path is not cloud-safe, `ANTHROPIC_API_KEY` guard is absent. Screenshots for the README have not been taken.

**Sprint:** Phase 9–10

---

## Technical Debt Assessment

### HIGH — Blocks completeness or correctness

| ID | Item | Location | Impact |
|---|---|---|---|
| TD-01 | 1 hardcoded NCCI PTP pair | `rules/ncci.py` | NCCI check is non-functional for 99.99% of code combinations |
| TD-02 | `rules/mue.py` is a stub | `rules/mue.py` | MUE denial risk undetected entirely |
| TD-03 | `rules/npi.py` is a stub | `rules/npi.py` | NPI denial risk undetected; short-circuit pattern broken |
| TD-04 | All agents are stubs | `agents/` | Core AI value proposition absent |
| TD-05 | RAG pipeline not built | `retrieval/` | Coverage agent cannot be built |
| TD-06 | 2 hardcoded code validity rules | `rules/code_validity.py` | Most dx-procedure conflicts and modifier issues undetected |

### MEDIUM — Limits quality or coverage

| ID | Item | Location | Impact |
|---|---|---|---|
| TD-07 | No manual claim intake | `app/components/claim_form.py` | Demo limited to 5 fixed claims |
| TD-08 | `test_rules.py` and `test_orchestrator.py` are stubs | `tests/` | MUE, NPI have no test coverage |
| TD-09 | No golden set evaluation | `tests/`, `data/synthetic/` | Cannot measure precision/recall |
| TD-10 | `db/audit.py` stub coexists with `audit_repository.py` | `db/` | Confusing dual-file situation |
| TD-11 | `ClaimIn` fields are untyped `list` | `rules/models.py` | Type checker cannot catch element type errors |
| TD-12 | No `.env` guard or `ANTHROPIC_API_KEY` check | `app/main.py` | Will crash mid-demo when agents are wired |

### LOW — Polish and future-proofing

| ID | Item | Location | Impact |
|---|---|---|---|
| TD-13 | `app/components/` all stubs | `app/components/` | `app/main.py` will grow unwieldy by Phase 5 |
| TD-14 | `requirements.txt` includes unused `chromadb`, `pydantic` | `requirements.txt` | Slower install; ~500MB native deps for unused lib |
| TD-15 | Citation edition is `"synthetic sample"` or `"(sample reference)"` | All rule modules | Not traceable to a real policy snapshot |
| TD-16 | No application logging | All modules | Debug information lost between sessions |
| TD-17 | Synthetic NPIs fail Luhn validation | `data/synthetic/sample_claims.json` | Will produce NPI findings when NPI check is wired |

### Re-evaluation: Hardcoded Rules

The hardcoded approach is acceptable for portfolio purposes — the interfaces are correct, the data loading is isolated, and the replacement path is explicit. What is *not* acceptable is presenting the 1 NCCI pair as "NCCI validation" without qualification. The right framing: "the NCCI check uses one illustrative edit pair; production would load the full ~250,000-pair CMS quarterly file."

### Re-evaluation: Policy Reference Approach

Sprint 3's local JSON approach is the right call for this sprint. The 5 entries make citations feel real and demonstrate the retrieval interface. The risk: adding more entries manually doesn't scale. The design is correctly oriented toward ChromaDB replacement. No action needed until Phase 4.

### Re-evaluation: Risk Scoring

`overall_risk()` is a pure function returning the highest severity present. This is correct for current data but does not implement the payer-specific CARC-weighted scoring described in the PRD. When the Denial Prevention Agent is built, `RiskAssessment.score` (a 0–100 numeric) needs to be computed there, not by `overall_risk()`.

### Re-evaluation: Architecture Concerns

The primary architectural concern is that `app/main.py` is accumulating all UI logic (currently ~420 lines). By Phase 5, with agent findings, progress indicators, and note display added, this file will be difficult to maintain. The `app/components/` modules should be populated incrementally as each phase adds new UI surface.

---

## Readiness Assessment

### Portfolio Demo — 62 / 100

**What works:** The app loads, runs a deterministic claim review, displays severity-ranked findings with full policy citation detail (title, source URL, section, effective date, excerpt), captures human decisions, and persists them to an append-only audit log. The "📄 View policy detail" panel with real CMS source URLs makes the citation feel evidence-backed. The governance story is demonstrable end-to-end.

**What is missing:** The AI layer. Every finding comes from a hardcoded rule. Cannot demonstrate "AI researches, humans decide" because AI doesn't research anything yet. If someone asks "show me an AI finding," the answer is nothing.

**Score rationale:** A polished, working, testable application with a sound architecture story earns above 50. Sprint 3 pushed this from 55 to 62 by making citations feel real. The ceiling is ~68 without at least one agent producing findings. Once a single LLM finding appears, this score jumps to 80+.

---

### Product Management Interview — 70 / 100

**Strengths:** The PRD is genuinely strong: problem framing (claims denial is a $262B/year industry problem), market context, P0/P1/P2 prioritization, user personas (specialist reviewer, compliance auditor), acceptance criteria per story, and a worked example. The build sequence demonstrates PM discipline — governance infrastructure before AI, deterministic before generative. Every major design decision is documented in `docs/Architecture_Decisions.md` with alternatives considered and tradeoffs stated.

**Gaps:** No live metrics dashboard. Cannot demonstrate batch review or triage queue (P1). PRD §14 performance targets (≥90% precision, ≥85% recall, ≤2min review time) cannot be evidenced. No user research documented.

**Score rationale:** Strong PRD + disciplined build sequence + documented tradeoffs earns 70. The gap to 80+ is primarily the absence of measurable outcomes and live P1 features.

---

### Director of Product Interview — 65 / 100

**Strengths:** The project demonstrates systems thinking: governance before AI is a strategic decision that reduces compliance risk and technical debt. The Citation enforcement model (repository layer, not UI) shows understanding of where invariants belong. The ADR format for architecture decisions shows communication maturity. The tech debt register with planned sprints shows roadmap accountability.

**Gaps:** A Director-level conversation will probe market sizing, competitive positioning, pricing, and go-to-market — none of which are in this repository. Will also ask about customer discovery and whether this solves a real workflow problem. The answer from this repo is: technically yes, but unvalidated.

**Score rationale:** The depth of the technical documentation and the clarity of tradeoff reasoning pushes this above 60. The gap is strategic context: market validation, competitive differentiation, and business model.

---

### AI Product Management Interview — 68 / 100

**Strengths:** The architectural decisions are exactly the ones an AI PM should be able to articulate: rule-before-LLM (determinism where determinism suffices), citation requirement (RAG grounds every claim), confidence thresholds and escalation, `finding_id` stability as a governance invariant, append-only audit as an explainability mechanism. The Sprint 3 decision — use curated policy references rather than build the RAG pipeline prematurely — demonstrates judgment about when to abstract ahead of need.

**Gaps:** No LLM is calling the Claude API. The RAG pipeline is fully stubbed. Cannot demonstrate retrieval quality, embedding strategy, chunking decisions, or agent reasoning empirically. An AI PM panel will ask "what did you learn from the first agent run?" and the answer today is "the agent hasn't run yet."

**Score rationale:** Clarity of AI architecture rationale raises this above 65. The ceiling lifts sharply (to 85+) once one agent is wired and the retrieval pipeline has been exercised.

---

### Healthcare AI Governance Demonstration — 78 / 100

**Strengths:** This is the project's strongest dimension. The governance stack is genuinely production-quality:

- Append-only audit log (INSERT only, no UPDATE or DELETE — enforced at the module level, not by convention)
- Citation required before any finding can reach the audit log (architectural enforcement in `save_decision()`)
- Named reviewer required — no anonymous decisions
- Override requires a documented reason — auditable
- Confidence threshold triggers escalation flag (non-blocking, visible)
- Full decision trail: timestamp, reviewer, finding_id, severity, decision, reason, model_version, prompt_version, citation_effective_date
- `finding_id` is SHA-256 stable — the same finding produces the same ID across all processes, making the audit log a genuine provenance trail
- CSV export for compliance workflows

**Gaps:** The AI that would need to be governed is not yet wired. Governance without AI to govern is infrastructure, not a live demonstration. Real CMS data would make citations traceable to actual published policy.

**Score rationale:** The governance architecture is complete, correct, and defensible. Score would reach 92+ once an AI agent is wired and its decisions are being governed by this infrastructure in a live demo.

---

### Startup MVP Readiness — 35 / 100

**What works:** The core architectural skeleton is correct and could support a real product. The data model is clean. The governance layer is more mature than most healthcare startups at seed stage.

**What is missing:** The primary user-facing feature (AI-powered claim review) is absent. Manual claim input doesn't exist. Only 5 synthetic claims are supported. No real CMS data. No performance measurement. Cannot be used by a real specialist for a real claim.

**Score rationale:** A startup MVP that cannot accept real input and cannot demonstrate its primary value proposition scores 35. The correct frame: this is a well-architected prototype, not an MVP. Reaching MVP requires completing Phase 3 (real rule data + claim intake), Phase 4 (retrieval), and Phase 5 (coverage agent) — roughly 10–15 more sessions.

---

## Competitive Assessment

### vs. Typical PM Portfolio Project

**Typical PM portfolio:** A Figma mockup or a low-fidelity prototype with a slide deck. No working software. No tests. No architecture documentation.

**This project:**
- Working software that runs and produces output
- 55 passing tests with zero mocks
- Comprehensive ADR documentation
- Genuine governance architecture (not demo governance)
- A technical debt register with planned sprints

**Verdict:** Strongly above average for a PM portfolio. Most PM portfolio projects do not have working code at all. The governance narrative and documentation suite are unusual positives. The gap to top-tier: no live AI, no metrics.

---

### vs. Typical AI Portfolio Project

**Typical AI portfolio:** A Jupyter notebook with a fine-tuned model or an OpenAI API wrapper with a chat UI. Often no tests. Rarely any governance. Citations are strings at best.

**This project:**
- Healthcare domain with genuine regulatory context (NCCI, LCD/NCD, MUE, PHI constraints)
- Governance-first architecture (unusual — most AI portfolios have no governance)
- Structured citations with enforcement (not just display strings)
- Documented agent architecture with clear replacement seams

**Weakness vs. typical AI portfolio:** No working LLM integration. A typical AI portfolio project will have at least one API call to a model producing output. This project has none yet.

**Verdict:** More sophisticated architecture and governance than the typical AI portfolio, but weaker on live AI demonstration. An interviewer who values engineering depth will rank this above a chat wrapper. An interviewer who wants to see "the AI working" will note the absence.

---

### vs. Typical Healthcare AI Portfolio Project

**Typical healthcare AI portfolio:** Either a pure academic project (model training, AUC scores, no product) or a basic RAG demo over synthetic medical records with no governance.

**This project:**
- Full product architecture, not just a model
- Genuine healthcare regulatory context (CMS, NCCI, LCD/NCD, MUE — not generic "medical AI")
- PHI protection by design (synthetic data only, explicit constraint)
- Governance stack a healthcare compliance reviewer would recognize (append-only log, citation enforcement, named reviewer, override documentation)
- Demo script calibrated for clinical operations, compliance, and PM audiences

**Weakness:** No actual AI producing healthcare-relevant findings yet. A health AI interviewer will probe: "What did the model get wrong? How did you handle hallucinations? How do you ensure citation accuracy?" These questions cannot be answered empirically yet.

**Verdict:** Strongest relative position against healthcare AI portfolios because governance and domain specificity are rare. This niche is less crowded than general AI portfolios.

---

## Recommended Next Milestone

**Build the Coverage Validation Agent with real LCD/NCD retrieval (Phases 4 + 5 combined).**

### Why This Is Highest Value

This is the feature that transforms the project from a rules engine with a governance wrapper into a demonstrable AI claim review copilot. Every interview-readiness gap — "show me an AI finding," "how do you handle hallucinations," "what did you learn from RAG retrieval" — closes with this milestone.

Specifically:
1. The "📄 View policy detail" panel currently shows structured data from a curated JSON file. After Phase 4+5, it shows a verbatim excerpt from an actual CMS LCD document, retrieved by semantic search. This is a qualitatively different claim.
2. The "no citation → no finding" rule becomes empirically testable: the agent will attempt to find a policy excerpt and either produce a finding (with citation) or suppress it (no retrieval hit). The governance architecture gets stress-tested.
3. Readiness scores jump: Portfolio Demo (~80), AI PM Interview (~85), Healthcare AI Governance (~92).

### Dependencies

- Phase 3 rule completion is *not* a hard prerequisite for the RAG pipeline. The coverage agent can be built in parallel with or before completing MUE/NPI/reference data.
- Hard dependencies: ChromaDB installed (already in `requirements.txt`), CMS Coverage API accessible (free, no auth), `ANTHROPIC_API_KEY` set.
- Recommended order: Phase 4 (ingest + chunk + index) → Phase 5 (agent + UI wiring). Phase 4 can complete in 1–2 sessions; Phase 5 in 2–3.

### Estimated Effort

- Phase 4 (retrieval pipeline): 2 sessions
- Phase 5 (coverage agent): 3 sessions
- Total: ~5 sessions

### Expected Impact

| Dimension | Before | After |
|---|---|---|
| Portfolio Demo score | 62 | ~82 |
| AI PM Interview score | 68 | ~85 |
| Healthcare AI Governance score | 78 | ~92 |
| "Show me an AI finding" question | ❌ Cannot | ✅ Can |
| RAG retrieval empirical discussion | ❌ Cannot | ✅ Can |
| Citation accuracy demonstrated | ❌ Synthetic | ✅ Real CMS text |

---

## Recommended Development Roadmap

### Next 5 Milestones (Priority Order)

| # | Milestone | Complexity | Key Deliverable | Score Impact |
|---|---|---|---|---|
| 1 | **Phase 4 — LCD/NCD Retrieval Pipeline** | Medium | ChromaDB index over real CMS LCDs; `retrieval/ingest.py`, `chunking.py`, `vector_store.py` | Unblocks agent layer |
| 2 | **Phase 5 — Coverage Validation Agent** | High | First LLM agent; cited medical necessity findings from retrieved policy | +20 on all scores |
| 3 | **Phase 3 — Complete Deterministic Layer** | Medium | Real NCCI CSV (~250k pairs), MUE stub → implementation, NPI Luhn + NPPES API, manual claim form | +8 on all scores |
| 4 | **Phase 7 — Orchestrator + Denial Prevention Agent** | Medium | Parallel dispatch, `RiskAssessment`, full 4-agent pipeline | Architecture story complete |
| 5 | **Phase 8 — Evaluation Framework** | Low | Golden set (20–30 claims), `pytest -m golden`, precision/recall report | Closes PRD §14 gap |

**Notes on ordering:**
- Phases 4 and 5 are prioritized ahead of Phase 3 because the AI demonstration value exceeds the rule completeness value for interview readiness.
- Phase 3 (manual claim form + real rule data) is milestone 3, not 1, because the architecture story lands better if the first live demo can show AI findings — even over the current 5 synthetic claims.
- Phase 6 (documentation review agent) and Phase 9–10 (publication, deployment) are excluded from the top 5 because their value is lower relative to the coverage agent and evaluation.

---

## Final Verdict

### 1. Is the project currently portfolio-worthy?

**Yes, with qualification.**

The project is portfolio-worthy as an architecture and governance showcase. The data model, audit system, and documentation suite are more sophisticated than most PM or AI PM portfolios. The project clearly demonstrates prioritization discipline, product judgment, and healthcare domain knowledge.

The qualification: it cannot yet demonstrate the product's primary value proposition. An interviewer who presses "show me the AI" will see nothing. The honest framing for the current state: *"I built the governance and data foundation first — here's why — and the AI layer is next."* That framing is defensible and, for the right audience, impressive. For an audience that wants to see a demo, it is a gap.

### 2. Is the project interview-worthy?

**Yes, for PM, Director of Product, and Healthcare AI Governance roles. Partially for AI PM roles.**

- **PM / Director PM interview:** Yes. The PRD, documentation, and architecture decisions provide rich material for 60+ minutes of substantive discussion.
- **Healthcare AI Governance:** Yes. The governance stack is production-quality and the conversation around citation enforcement, append-only audit, and confidence escalation is deep and defensible.
- **AI PM interview:** Partially. The architecture rationale is strong, but "what did the model produce?" and "what did you learn from retrieval?" cannot be answered yet. Recommend completing Phase 5 before an AI PM panel.

### 3. What is the single most important feature still missing?

**The Coverage Validation Agent with real LCD/NCD retrieval.**

This is the feature that makes the project demonstrably different from a rules engine. It turns "AI researches, humans decide" from a tagline into a live demonstration. It exercises the citation enforcement model against real retrieved text rather than curated JSON. It enables every empirical conversation an AI PM interviewer will want to have. Nothing else on the roadmap comes close to its interview impact per session of effort.

---

*This document was generated as a comprehensive project assessment. It reflects the state of the repository as of Sprint 3 completion (commit `89024d8`). No application code was modified.*
