# Repository Status Report
## Denial Prevention Copilot

**Date:** June 2026  
**Repository:** denial-prevention-copilot  
**Branch:** main  
**Last commit:** Sprint 3 — Policy intelligence foundation (local policy reference dataset, citation detail view, audit schema migration)

---

## Executive Summary

The Denial Prevention Copilot is a portfolio-grade AI copilot for pre-submission healthcare claim review. The core thesis: move denial management upstream by reviewing claims before they are submitted, with every finding backed by a cited policy source and every decision made by a human.

Five development phases are complete:

| Phase | Status | Commit |
|---|---|---|
| Environment Setup | ✅ Complete | `11f62cf` |
| Deterministic Claim Review v0.1 | ✅ Complete | `cf322d9` |
| Pre-Audit Model Refactor | ✅ Complete | `dc681f2` |
| Governance & Audit Logging | ✅ Complete | `ee45738` |
| Policy Intelligence Foundation | ✅ Complete | Sprint 3 |

**What works today:** A Streamlit application that loads synthetic claims, runs deterministic NCCI bundling and diagnosis-to-procedure conflict checks, produces severity-ranked findings backed by structured policy references, captures human accept/override decisions with required reasons, and persists every decision (including citation effective date) to an append-only SQLite audit log with CSV export. Each finding card shows a full "📄 View policy detail" panel with title, CMS source URL, section, edition, and policy excerpt drawn from a curated local dataset.

**What is not yet built:** The LLM agent layer (coverage validation, documentation review, denial prevention synthesis), the RAG retrieval pipeline over real LCD/NCD data, the MUE and NPI rule checks, and the manual claim intake form. The local policy dataset (`policy_examples.json`) is a curated placeholder — real CMS/NCCI/LCD/NCD ingestion is a future replacement point.

**Test coverage:** 55 tests, all passing. Zero mocks — the rule layer tests use inline data; the audit and policy tests use temporary databases and the local JSON file.

---

## Current Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  Streamlit UI  (app/main.py)                                    │
│                                                                 │
│  Sidebar: Reviewer Name                                         │
│  ┌──────────────────────┐  ┌──────────────────────────────┐    │
│  │  🔍 Review Claim tab │  │  📋 Audit Trail tab          │    │
│  │                      │  │                              │    │
│  │  Claim Selector      │  │  Filter by claim / reviewer  │    │
│  │  Claim Details       │  │  Decision table (DataFrame)  │    │
│  │  [Review Claim btn]  │  │  [Export to CSV]             │    │
│  │                      │  │                              │    │
│  │  Findings Panel      │  └──────────────────────────────┘    │
│  │  ├ Finding Card      │                                       │
│  │  │  severity badge   │                                       │
│  │  │  issue + rec      │                                       │
│  │  │  citation caption │                                       │
│  │  │  📄 policy detail │  ← Sprint 3                           │
│  │  │  [Accept][Override│                                       │
│  │  │  [💾 Save Decision│                                       │
│  │  └─────────────────  │                                       │
│  └──────────────────────┘                                       │
└──────────────────────┬──────────────────────────────────────────┘
                       │ calls
                       ▼
┌──────────────────────────────────────┐
│  rules/rule_engine.py                │
│  load_claim() → review_claim()       │
│  _make_finding_id() [SHA-256]        │
│  overall_risk()                      │
└────────┬─────────────────────────────┘
         │ calls
         ├──────────────────────────────────────────┐
         ▼                                          ▼
┌─────────────────────┐              ┌──────────────────────────┐
│  rules/ncci.py      │              │  rules/code_validity.py  │
│  IMPLEMENTED        │              │  IMPLEMENTED             │
│  1 PTP edit pair    │              │  2 rule tables           │
│  (hardcoded)        │              │  (hardcoded)             │
└─────────────────────┘              └──────────────────────────┘

         ┌──────────── STUBS (docstring only) ──────────────┐
         │  rules/mue.py        MUE table lookup            │
         │  rules/npi.py        NPPES live API client       │
         │  agents/orchestrator.py                          │
         │  agents/coding_validation.py                     │
         │  agents/coverage_validation.py  ← RAG + Claude  │
         │  agents/documentation_review.py ← LLM           │
         │  agents/denial_prevention.py    ← synthesis      │
         │  retrieval/ingest.py            ← CMS API        │
         │  retrieval/chunking.py                           │
         │  retrieval/vector_store.py      ← ChromaDB       │
         └──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  db/audit_repository.py   IMPLEMENTED                        │
│  AuditDecision dataclass  (18 fields)                        │
│  AuditRepository:                                            │
│    initialize_database()  → CREATE TABLE IF NOT EXISTS       │
│    save_decision()        → INSERT only (append-only)        │
│    get_decisions()        → SELECT with optional filters     │
│    export_decisions_csv() → CSV string                       │
│                                                              │
│  db/audit.db              SQLite file (gitignored)           │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Data                                                         │
│  data/synthetic/sample_claims.json   5 synthetic claims      │
│  data/reference/policy_examples.json 5 policy references ←S3 │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  retrieval/policy_repository.py   IMPLEMENTED ← Sprint 3     │
│  load_policy_references()  → reads policy_examples.json      │
│  find_policy_by_document_id()  → O(n) scan by doc_id         │
│  find_policies_by_codes()      → match by CPT/ICD/modifier   │
│  get_citation_detail()         → enrich Citation for UI       │
│                                                              │
│  Future replacement: swap _load_policy_references() with     │
│  ChromaDB query when ingest.py + vector_store.py are built   │
└──────────────────────────────────────────────────────────────┘
```

**Legend:** IMPLEMENTED = functional code | STUBS = docstring-only skeletons

---

## Completed Features

### Rule Layer
- **NCCI PTP bundling check** — detects when a component code (col 2) is billed with its comprehensive code (col 1); returns HIGH severity finding with modifier indicator noted
- **Diagnosis-to-procedure conflict** — flags Z00.00 (routine exam) billed with problem-oriented E/M codes (99202–99215)
- **Missing modifier 25** — flags problem E/M billed in a preventive visit context without modifier 25
- **Structured citations** — every finding carries `Citation(source, doc_id, section, edition, effective_date, excerpt)`; no citation → finding suppressed
- **Stable finding identity** — SHA-256 deterministic `finding_id` across all runs and processes
- **Source provenance** — every finding carries `source: "rule_layer"` (ready for agent layer extension)
- **Severity ranking** — findings sorted HIGH → MEDIUM → LOW

### Streamlit UI
- Claim selector (5 synthetic claims from JSON)
- Claim details expander (payer, NPI, CPT, ICD-10, modifiers, POS)
- Color-coded finding cards with severity badges
- "📄 View policy detail" expander per finding: title, CMS source URL, section, edition, effective date, policy excerpt, implementation notes (Sprint 3)
- Accept / Override decision controls (override requires non-empty reason)
- Reviewer name input (sidebar, required to save)
- "Manual Review Recommended" badge for confidence < 70%
- Save Decision button per finding (appears after accept/override decision is made)
- Audit Trail tab with filter-by-claim-id and filter-by-reviewer
- Export to CSV download button
- Clean claim state ("no denial risks identified" with checks run listed)

### Governance & Audit Log
- SQLite append-only `audit_decisions` table (18 columns, no UPDATE/DELETE ever)
- `AuditRepository` abstraction — UI never calls sqlite3 directly
- Governance validation in `save_decision()`:
  - Rejected if `finding_id` is empty
  - Rejected if `citation_source` or `citation_doc_id` is empty
  - Rejected if `user_decision == "overridden"` and `override_reason` is empty
- Per-finding save confirmation ("✅ Saved to audit log")
- Full audit trail: timestamp, claim_id, finding_id, severity, decision, reason, reviewer, model_version, prompt_version, citation_effective_date (Sprint 3)
- Backward-compatible `ALTER TABLE` migration for `citation_effective_date` on existing databases (Sprint 3)

### Policy Intelligence (Sprint 3)
- `data/reference/policy_examples.json` — 5 curated policy references (NCCI PTP 80048/80053, ICD-10 Z00.00, Modifier 25, LCD venipuncture, MUE panel limits)
- `retrieval/policy_repository.py` — JSON-backed service: `find_policy_by_document_id`, `find_policies_by_codes`, `get_citation_detail`
- Rule modules updated: doc_ids now reference `policy_examples.json` entries with real effective dates and substantive excerpts

### Tests
- 55 tests, all passing, < 0.1 second runtime
- No network calls, no external dependencies, no mocks
- `tests/test_rule_engine.py` — 20 tests covering NCCI, dx conflict, modifier, risk scoring, finding_id stability, Citation structure
- `tests/test_audit.py` — 15 tests covering persistence, validation, filtering, CSV export
- `tests/test_policy_repository.py` — 20 tests covering JSON loading, document_id lookup, code-based lookup, citation resolution, audit migration (Sprint 3)

---

## Completed PRD Requirements

| PRD Section | Requirement | Status |
|---|---|---|
| §5 Principle 1 | Assist, don't replace — no autonomous action | ✅ Human decision required for every finding |
| §5 Principle 2 | Evidence before recommendation — no finding without citation | ✅ Enforced in AuditRepository.save_decision() |
| §5 Principle 3 | Deterministic before generative — rule layer first | ✅ Rules run before any LLM (LLM not yet wired) |
| §5 Principle 4 | Human accountability — named specialist, override requires reason | ✅ Reviewer name + mandatory reason for overrides |
| §5 Principle 5 | Governance by design — audit trail is MVP scope, not later | ✅ Append-only audit log implemented |
| §6 P0 | Deterministic validation: NCCI PTP pairs | ✅ Implemented (1 edit pair) |
| §6 P0 | Denial risk assessment with severity, fix, citation | ✅ HIGH/MEDIUM/LOW with structured Citation |
| §6 P0 | Accept / override workflow with required override reason | ✅ Implemented with confirm-before-save |
| §6 P0 | Audit log: inputs, findings, citations, human decision, timestamps | ✅ 18-column audit_decisions table |
| §6 P1 | Confidence score per finding with low-confidence escalation flag | ✅ Confidence field + "Manual Review Recommended" badge |
| §7 Story 1 | Findings include severity, issue, recommended fix, citation | ✅ All four present on every finding |
| §7 Story 1 | Clean claim explicitly marked with checks run | ✅ "CLEAN — no denial risks identified" |
| §7 Story 2 | Citation shows source excerpt | ✅ "📄 View policy detail" expander with title, source URL, section, edition, effective date, and excerpt |
| §7 Story 3 | Override requires free-text reason, captured in audit log | ✅ With reviewer name and timestamp |
| §7 Story 4 | Exportable per-claim audit log | ✅ CSV export in Audit Trail tab |
| §12 | Immutable log of inputs, findings, citations, decisions | ✅ Append-only SQLite, no UPDATE/DELETE |
| §12 | PHI protection — synthetic data only | ✅ All claims are synthetic, no PHI anywhere |

---

## Missing PRD Requirements

### P0 — Not Yet Implemented (blocks MVP completeness)

| Requirement | PRD Section | Gap |
|---|---|---|
| Claim intake form (manual entry + CSV upload) | §6 P0 | UI reads from JSON file only; no manual input form |
| NPI Registry lookup (live NPPES API) | §6 P0, §10 | `rules/npi.py` is a stub |
| MUE limits check | §6 P0, §10 | `rules/mue.py` is a stub |
| Code validity: ICD-10-CM billability check | §6 P0 | Only Z00.00 rule is implemented; no reference file loaded |
| Code validity: HCPCS Level II validity | §6 P0 | Not implemented |
| Coverage check via CMS NCD/LCD (RAG) | §6 P0 | `agents/coverage_validation.py` is a stub; no retrieval pipeline |
| Medical necessity reasoning (LLM) | §6 P0 | Agents not wired; no Claude API calls |
| Orchestrator: parallel agent dispatch | §9 | `agents/orchestrator.py` is a stub |
| Denial Prevention Agent: risk synthesis | §9 | `agents/denial_prevention.py` is a stub |
| Real NCCI PTP data from CMS quarterly file | §10 | Only 1 hardcoded pair; no CSV loader |

### P1 — Not Yet Implemented

| Requirement | PRD Section | Gap |
|---|---|---|
| Documentation review agent (clinical note) | §6 P1 | `agents/documentation_review.py` is a stub |
| Batch review / CSV upload + triage queue | §6 P1 | Single claim only; no batch mode |

### P2 — Explicitly Deferred

| Requirement | PRD Section |
|---|---|
| Commercial payer policy corpus | §6 P2 |
| Denial pattern analytics across claims | §6 P2 |

### Success Metrics — Not Yet Trackable

| Metric | PRD §14 | Status |
|---|---|---|
| Finding precision ≥ 90% on golden set | §14 | Golden set not built; `pytest -m golden` command documented but fixture missing |
| Finding recall ≥ 85% on golden set | §14 | Same |
| Citation coverage = 100% | §14 | Enforced architecturally; no automated measurement |
| Average review time ≤ 2 min | §14 | Not measured |
| Escalation rate | §14 | Not measured |

---

## Technical Debt Register (Summary)

Full register in `docs/Technical_Debt_Register.md`.

| ID | Item | Priority | Status |
|---|---|---|---|
| TD-R1 | `Finding.citation` was flat string | High | ✅ Resolved |
| TD-R2 | No stable finding identity | High | ✅ Resolved (SHA-256) |
| TD-R3 | Positional session state keys | High | ✅ Resolved |
| TD-R4 | Widget key reused as storage slot (override reason) | High | ✅ Resolved |
| TD-R6 | Citation doc_ids were opaque synthetic strings | High | ✅ Resolved (Sprint 3) |
| TD-R7 | No citation title, source URL, or notes in UI | Medium | ✅ Resolved (Sprint 3) |
| TD-R8 | `citation_effective_date` not persisted in audit log | High | ✅ Resolved (Sprint 3) |
| TD-05 | `rules/mue.py` stub | High | ⚠ Open |
| TD-06 | `rules/npi.py` stub | High | ⚠ Open |
| TD-07 | 1 hardcoded NCCI PTP edit pair | High | ⚠ Open |
| TD-08 | 2 hardcoded coding rules (no reference files) | High | ⚠ Open |
| TD-09 | All agents are stubs | High | ⚠ Open |
| TD-10 | RAG retrieval pipeline not built | High | ⚠ Open |
| TD-11 | No manual claim intake form | Medium | ⚠ Open |
| TD-12 | `db/audit.py` stub still present alongside `audit_repository.py` | Low | ⚠ Open |
| TD-13 | `ClaimIn` fields are untyped `list` | Low | ⚠ Open |
| TD-14 | `tests/test_rules.py` and `tests/test_orchestrator.py` are stubs | Medium | ⚠ Open |
| TD-15 | `app/components/` are all stubs | Low | ⚠ Open |
| TD-16 | No `.env` guard at startup | Low | ⚠ Open |
| TD-17 | Golden set evaluation (`pytest -m golden`) not implemented | Medium | ⚠ Open |

---

## Recommended Next Milestone

**Milestone: Complete the Deterministic Layer + Claim Intake Form**

Before wiring the LLM agent layer, close the gaps in the rule layer and claim intake. This milestone has three goals:

1. **Real NCCI/MUE data** — Load the actual CMS quarterly PTP and MUE CSV files into `rules/ncci.py` and `rules/mue.py`. This replaces the one hardcoded edit pair with ~250,000+ real edit pairs and adds MUE unit-limit checking.

2. **Live NPI validation** — Implement `rules/npi.py` with the NPPES API client and Luhn check digit validation. A deactivated NPI is a hard denial trigger and the most common clean-claim blocker.

3. **Manual claim intake** — Replace the JSON file selector with a manual form in `app/components/claim_form.py`. Without this, the demo cannot accept arbitrary input, limiting its value in live demonstrations.

**Why before agents:** The agent layer depends on the rule layer completing first (per the architecture and PRD). Building agents over incomplete rule data produces misleading findings. Real NCCI/MUE data also creates a much richer demo: showing findings from 250k+ real edit pairs is substantively more impressive than one hardcoded pair.

**Estimated scope:** 4–6 implementation sessions. `test_rules.py` (currently stub) should reach 20+ tests covering MUE, NPI, and reference-data loading.

---

## Readiness Assessment

### Portfolio Demo — 62 / 100

**What works:** The UI is polished and tells the architecture story clearly. Findings display with severity badges, full citation detail panels (title, CMS source URL, section, edition, effective date, policy excerpt), and the audit trail. Clicking "📄 View policy detail" shows a real CMS source URL and policy-level language — the app now reads as evidence-backed rather than purely synthetic. The governance story (append-only log, citation required, human-in-loop) is demonstrable end-to-end.

**What is missing:** The AI isn't wired. Only 3 rule-based findings are possible. The policy dataset is curated (5 entries) rather than sourced live from CMS. If asked "show me an LLM finding," there is nothing to show.

**Score rationale:** Sprint 3 raised the score from 55 → 62 by making citations feel real (actual source URLs, policy titles, substantive excerpts) and adding 20 more tests. The ceiling remains ~65 until at least one agent is wired and producing findings from real CMS data.

---

### Product Management Interview — 68 / 100

**Strengths:** The PRD itself is strong — problem framing, market context, prioritization (P0/P1/P2), user personas, acceptance criteria, and a worked example. The implementation demonstrates prioritization discipline: governance infrastructure was built *before* the AI, not after. The human-in-loop and override requirements reflect genuine product thinking about healthcare workflows.

**Gaps:** No metrics dashboard or measurement infrastructure. No batch mode to show workflow scale. Cannot yet demonstrate the agent layer performance targets (≥90% precision, ≥85% recall) from PRD §14. Cannot demonstrate review time ≤ 2 minutes (the claim is synthetic and trivial).

**Score rationale:** Strong PRD + coherent build sequence + explainable tradeoffs earns a PM interview score above 65. Gap to 100 is primarily the unimplemented P0 features and the absence of any live metrics.

---

### AI Product Management Interview — 65 / 100

**Strengths:** The architecture decisions are exactly the ones an AI PM should be able to explain: rule layer before LLM (determinism where determinism suffices), citation requirement (RAG grounds every claim), confidence thresholds and escalation, finding_id stability as a governance invariant, append-only audit as an explainability mechanism. These are not generic AI PM talking points — they are design decisions with real rationale in this specific healthcare context.

**Gaps:** No LLM is currently calling the Claude API. The RAG pipeline is fully stubbed. Cannot demonstrate retrieval quality, citation accuracy, or agent reasoning in practice. The evaluation framework (golden set, precision/recall) is planned but unbuilt. An AI PM interview panel will ask "show me a finding the LLM produced" and the answer today is "not yet."

**Score rationale:** Architectural clarity and governance maturity push the score above 60. The ceiling is the absence of any working AI component to discuss empirically. The score is 65 rather than lower because the reasoning about *why* AI was deferred is itself a strong talking point.

---

### Healthcare AI Governance Demonstration — 72 / 100

**Strengths:** This is the strongest dimension. The governance design is genuinely production-quality:
- Append-only audit log (INSERT only, no UPDATE or DELETE, ever)
- Citation required before any finding can be saved (architectural enforcement, not convention)
- Named reviewer required — no anonymous decisions
- Override requires a reason — documented and auditable
- Confidence threshold triggers "Manual Review Recommended" (non-blocking, visible)
- Full decision trail: timestamp, reviewer, finding, citation, decision, reason, model version
- CSV export for compliance audit workflows

**Gaps:** The AI that would need to be governed is not yet wired. Governance without an AI to govern is infrastructure, not a live demonstration. Real CMS data (LCDs with actual effective dates, real NCCI editions) would make citations traceable to actual published policy rather than "synthetic sample."

**Score rationale:** The governance architecture is complete and correct. The score would reach 90+ once at least one AI agent is wired and producing findings that exercise the citation requirement against real retrieved text.

---

## Recommended Development Roadmap

See `docs/Roadmap.md` for the full phased plan.

| Phase | Description | Key Deliverable |
|---|---|---|
| ✅ 0 | Environment Setup | Skeleton, requirements, CLAUDE.md |
| ✅ 1 | Deterministic Claim Review | Rule layer, Streamlit UI, 20 tests |
| ✅ 1.5 | Pre-Audit Model Refactor | Citation dataclass, finding_id, source field |
| ✅ 2 | Governance & Audit Logging | AuditRepository, audit trail, 15 tests |
| ✅ 2.5 | Policy Intelligence Foundation | policy_examples.json, policy_repository.py, citation detail view, 20 tests |
| 3 | Complete Deterministic Layer | Real NCCI/MUE CSV loaders, NPI API, claim intake form |
| 4 | LCD/NCD Retrieval Pipeline | CMS API ingestion, ChromaDB, section-aware chunking |
| 5 | Coverage Validation Agent | RAG + Claude API, medical necessity findings with citations |
| 6 | Documentation Review Agent | LLM analysis of clinical note text |
| 7 | Orchestrator + Denial Prevention Agent | Parallel dispatch, RiskAssessment synthesis |
| 8 | Evaluation Framework | Golden set, precision/recall, `pytest -m golden` |
| 9 | Portfolio Publication | Polished README, screenshots, public GitHub |
| 10 | Streamlit Cloud Deployment | Live public URL, env var management |

---

## Single Highest-Value Next Feature

**Coverage Validation Agent with RAG over real LCD/NCD data.**

This is the feature that transforms the project from a rules engine with governance infrastructure into a demonstrable AI claim review copilot.

**Why this feature:**

1. **It closes the most important gap in the demo.** Today every finding comes from a hardcoded rule. The Coverage Validation Agent would produce findings from retrieved CMS policy text, demonstrating the core RAG architecture — the thing that makes this product different from a clearinghouse scrubber.

2. **It exercises the citation requirement end-to-end.** The "no citation → no finding" principle (PRD §5 Principle 2) exists but cannot currently be stress-tested because all citations come from hardcoded rule tables. A live RAG retrieval forces the system to find or not find a policy excerpt, making the citation requirement a real architectural constraint rather than a convention.

3. **It unlocks the AI PM interview talking points empirically.** Right now the retrieval design, chunking strategy, and confidence scoring can only be *described*. With the Coverage Validation Agent wired, they can be *demonstrated*.

4. **It is the highest-difficulty reasoning task in the system** (per CLAUDE.md), which means it is also the most impressive to show. NCCI bundling is a lookup. Medical necessity determination against a specific LCD for a specific diagnosis-procedure pair requires genuine reasoning over policy text.

5. **The foundation is already built for it.** `retrieval/ingest.py`, `retrieval/chunking.py`, and `retrieval/vector_store.py` are designed stubs with clear interfaces. `agents/coverage_validation.py` has a complete docstring specification. The `Finding` and `Citation` models are already audit-ready. The first agent can be built directly from these stubs without any model changes.

**Prerequisite before building it:** Complete Phase 3 (LCD/NCD ingestion pipeline) so the Coverage Agent has indexed policy text to retrieve against.
