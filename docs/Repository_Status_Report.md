# Repository Status Report — Denial Prevention Copilot

**Generated:** 2026-06-15
**Sprint:** 5 complete (Phase 2.8 shipped)
**Branch:** main
**Last commit:** Sprint 5 — File-backed NCCI PTP lookup (~1.73M active edit pairs, CMS v322r0)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture](#2-current-architecture)
3. [Implemented Features](#3-implemented-features)
4. [PRD Traceability Matrix](#4-prd-traceability-matrix)
5. [Remaining Gaps](#5-remaining-gaps)
6. [Technical Debt Assessment](#6-technical-debt-assessment)
7. [Readiness Assessment](#7-readiness-assessment)
8. [Competitive Assessment](#8-competitive-assessment)
9. [Recommended Next Milestone](#9-recommended-next-milestone)
10. [Recommended Development Roadmap](#10-recommended-development-roadmap)
11. [Final Verdict](#11-final-verdict)

---

## 1. Executive Summary

### Maturity

The Denial Prevention Copilot is a **well-architected early prototype** with a complete structural skeleton, a fully operational governance/audit layer, and now a production-grade NCCI PTP rule engine backed by real CMS reference data. The project has completed 7 of 11 planned phases (Phases 0 through 2.8). The application runs end-to-end — a claim goes in, deterministic rules fire against real CMS NCCI edits, findings are displayed with full v322r0 citations, and a human decision is written to an append-only audit log. The core AI differentiator (LLM agents, RAG pipeline) remains in stub form, but the deterministic layer now has its first real data source.

### MVP Completion: ~40–45%

The project has strong bones and the first real meat. The scaffolding is production-quality; NCCI bundling detection is now genuine. The intelligence layer is not yet started.

### Strengths

- **Governance-first design:** Citation as a first-class dataclass, SHA-256 finding IDs, append-only SQLite, human-in-loop enforcement — these are production-grade governance patterns built before any LLM exists. This is architecturally rare and directly addresses the PRD governance controls requirement (P0).
- **Clean separation of concerns:** Rule layer → orchestrator → agents → denial prevention is enforced at every level. `rule_engine.py` calls no LLM; `agents/` calls no DB. This modularity makes each layer independently testable and replaceable.
- **Decision record discipline:** 11 Architecture Decision Records written (ADR-011 added for file-backed NCCI), deferral triggers documented, future replacement points mapped. This is unusually rigorous for a prototype.
- **127 tests, all passing:** Tests now cover NCCI loader (44 tests), rule engine, audit governance, claim intake, and policy repository. The `tests/test_ncci_loader.py` file is substantive, not a stub.
- **Real NCCI PTP edits:** Sprint 5 replaced the 1-pair hardcoded lookup with a file-backed loader reading CMS quarterly xlsx files. ~1.73 million active edit pairs across 4 files (ccipra-v322r0-f1 through f4). Modifier 0/1/9 semantics handled. Bidirectional lookup. `functools.lru_cache` for process-lifetime performance. Synthetic fallback when CMS files absent.
- **Manual claim intake:** Sprint 4 added a full service-line coding grid (CPT, ICD-10, modifiers, units, POS, NPI, payer) with a worked example, deduplication, and PHI-guard caption. This makes the app demonstrable with real-looking synthetic claims.

### Key Gaps

- **All four PRD agents are stubs** — `agents/` contains only docstrings. No LLM call has been made.
- **Rule data mostly synthetic** — NCCI is now real (~1.73M pairs). Code validity still has 2 hardcoded rules. MUE is a stub. NPI has no Luhn check.
- **RAG pipeline not built** — `retrieval/chunking.py`, `retrieval/ingest.py`, `retrieval/vector_store.py` are empty modules. No CMS LCD/NCD has been ingested.
- **Accuracy unverifiable** — The PRD targets ≥90% precision and ≥85% recall. With no agents, these cannot be evaluated.

---

## 2. Current Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  app/main.py (Streamlit UI)                                             │
│  ┌──────────────────────────┐  ┌──────────────────────────────────────┐│
│  │  Sample Claim Mode        │  │  Manual Claim Entry Mode             ││
│  │  (hardcoded sample dict) │  │  (claim_intake.py service-line grid) ││
│  └──────────┬───────────────┘  └──────────────┬───────────────────────┘│
│             └─────────────────┬────────────────┘                        │
│                               ▼                                         │
│                  rule_engine.load_claim()                               │
│                  rule_engine.review_claim()                             │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                    ┌───────────▼───────────────┐
                    │   rules/rule_engine.py     │
                    │   (synchronous dispatcher) │
                    └───┬───────────────────┬───┘
                        │                   │
              ┌─────────▼────┐    ┌─────────▼────────┐
              │ rules/ncci.py│    │rules/code_        │
              │ + ncci_loader│    │validity.py        │
              │ (~1.73M pairs│    │(2 hardcoded rules)│
              │              │    │(2 hardcoded rules)│
              └─────────┬────┘    └─────────┬────────┘
                        └────────┬──────────┘
                                 │  list[Finding]
                    ┌────────────▼──────────────┐
                    │  Finding stamping:         │
                    │  finding_id = SHA-256      │
                    │  (claim_id:rule:issue)[:12]│
                    └────────────┬──────────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │  app/main.py findings panel│
                    │  (severity, issue, cite,  │
                    │   recommendation, excerpt) │
                    └────────────┬──────────────┘
                                 │  Human decision
                    ┌────────────▼──────────────┐
                    │  db/audit_repository.py    │
                    │  AuditRepository           │
                    │  .save_decision()          │
                    │  (governance enforced)     │
                    └────────────┬──────────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │  SQLite audit.db           │
                    │  audit_decisions table     │
                    │  (append-only, no UPDATE)  │
                    └───────────────────────────┘

─ ─ ─ ─ ─ ─ ─ STUB LAYER (not yet active) ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─

  agents/orchestrator.py ─────► agents/coding_validation.py   [STUB]
                         ─────► agents/coverage_validation.py [STUB]
                         ─────► agents/documentation_review.py[STUB]
                         ─────► agents/denial_prevention.py   [STUB]

  retrieval/vector_store.py ──► retrieval/ingest.py           [STUB]
                            ──► retrieval/chunking.py         [STUB]

  rules/mue.py                                                [STUB]
  rules/npi.py                                                [STUB]
  app/components/             findings_panel, claim_form, audit_view [STUB]
```

### Component Responsibilities (Implemented)

| Component | File | Status | Responsibility |
|---|---|---|---|
| UI (two modes) | `app/main.py` | Active | Streamlit app: sample mode + manual claim entry, findings display, human decision panel |
| Claim intake | `app/claim_intake.py` | Active | Build `ClaimIn` from service-line grid; payer lookup; NPI format check; code normalization |
| Rule engine | `rules/rule_engine.py` | Active | Dispatch to all rule modules; stamp SHA-256 finding_id; sort HIGH→MEDIUM→LOW |
| NCCI PTP check | `rules/ncci.py`, `rules/ncci_loader.py` | Active | File-backed loader; ~1.73M active pairs from CMS xlsx (v322r0); synthetic fallback when files absent |
| Code validity | `rules/code_validity.py` | Partial | 2 hardcoded rules (Z00.00 + problem E/M conflict; missing modifier 25) |
| Shared models | `rules/models.py` | Active | `ClaimIn`, `Citation`, `Finding` dataclasses |
| Audit repository | `db/audit_repository.py` | Active | `AuditDecision` dataclass; append-only SQLite; governance enforcement at save |
| Policy repository | `retrieval/policy_repository.py` | Partial | JSON-backed policy lookup; ChromaDB-compatible public interface; 5 synthetic entries |

### Data Flow (Active Path)

```
User enters claim (manual grid or sample)
  → build_manual_claim() normalizes codes, deduplicates, adds payer_id
  → rule_engine.load_claim() constructs ClaimIn
  → rule_engine.review_claim():
      ncci.check_ncci_pairs()      → 0–N Findings (real CMS ~1.73M pairs, v322r0)
      code_validity.check_code_validity() → 0–N Findings
      Findings sorted HIGH → MEDIUM → LOW
      finding_id stamped: SHA-256(claim_id:rule:issue)[:12]
  → app/main.py renders findings panel (severity badge, issue, recommendation, citation excerpt)
  → Human selects Approve / Deny / Escalate + optional override reason
  → audit_repository.save_decision() enforces:
      - finding_id required
      - citation required (doc_id, section, effective_date)
      - override_reason required when decision overrides HIGH finding
  → SQLite INSERT into audit_decisions (never UPDATE)
  → CSV export available on demand
```

### Audit Flow

Every claim decision produces one `AuditDecision` row per finding:

```
AuditDecision fields:
  claim_id, reviewer_name, finding_id           — identity
  decision ("Approve"|"Deny"|"Escalate")         — action
  override_reason                                — required if overriding HIGH
  citation_doc_id, citation_section              — source traceability
  citation_effective_date                        — temporal traceability
  severity, issue, recommendation               — finding content
  source_agent, confidence                       — agent metadata
  payer, cpt_codes, icd10_codes, modifiers      — claim snapshot
  timestamp                                      — ISO-8601 immutable
```

### Citation Flow

Citations are first-class dataclasses (`rules/models.py:Citation`), not strings:

```
Citation(
  source         → "NCCI PTP" / "ICD-10-CM" / "LCD" / ...   (human label)
  doc_id         → "NCCI_PTP_2026Q1"                          (DB key)
  section        → "Table Column 1/Column 2, Chapter 1§D"    (specific section)
  edition        → "NCCI Policy Manual Q1 2026"              (version)
  effective_date → "2024-01-01"                              (ISO-8601)
  excerpt        → verbatim policy text shown in UI          (optional)
)
```

Every `Finding` carries exactly one `Citation`. Rule layer citations are synthetic samples. Agent layer citations (when built) must be retrieved from ChromaDB. Findings without a verifiable citation are suppressed by design.

---

## 3. Implemented Features

### Feature 1: Deterministic Rule Engine

| Attribute | Value |
|---|---|
| Status | Partial — NCCI now real; code validity still synthetic |
| Files | `rules/rule_engine.py`, `rules/ncci.py`, `rules/ncci_loader.py`, `rules/code_validity.py`, `rules/models.py` |

The rule engine dispatches to all registered rule modules in a deterministic, synchronous pattern. Adding a new rule module requires one import and one function call — no registration framework needed. SHA-256 finding IDs are stamped post-dispatch so rule modules don't need claim context.

**What works:** Architecture, dispatch pattern, finding aggregation, severity sorting, ID stamping. NCCI PTP checks now use real CMS quarterly data (~1.73M active pairs, v322r0 effective 2026-07-01). `functools.lru_cache` on `_build_edit_table()` means xlsx files load once per process (~54s first load, then O(1)). Bidirectional lookup, modifier 0/1/9 semantics, and a synthetic fallback when xlsx files are absent.
**What's fake:** Code validity has 2 of thousands of rules. MUE module is a stub. NPI module is a stub (format-only check in `claim_intake.py`).

### Feature 2: Citation System (First-Class Dataclass)

| Attribute | Value |
|---|---|
| Status | Complete (rule layer); Not started (agent layer) |
| Files | `rules/models.py:Citation`, `rules/ncci.py`, `rules/code_validity.py`, `db/audit_repository.py` |

`Citation` is a first-class dataclass with six fields mapping 1:1 to the audit schema columns. This was a deliberate ADR-002 decision made before the audit database was built, ensuring every rule finding carries traceable provenance. The UI renders `citation.excerpt` inline under each finding.

**What works:** Schema design, UI rendering, audit storage, field-level mapping.
**What's fake:** `edition` fields say "sample reference" throughout; `effective_date` is hardcoded.

### Feature 3: Human Review Panel

| Attribute | Value |
|---|---|
| Status | Complete |
| Files | `app/main.py` (~570 lines) |

The findings panel shows severity badge, issue text, recommendation, and citation excerpt for each finding. The human decision panel offers Approve / Deny / Escalate with an optional override reason. Governance is enforced: a HIGH-severity finding overridden without a reason is rejected at save time by `AuditRepository`.

### Feature 4: Append-Only Audit Trail

| Attribute | Value |
|---|---|
| Status | Complete |
| Files | `db/audit_repository.py`, `db/audit.py` |

`AuditRepository.save_decision()` writes only INSERT. No UPDATE, no DELETE, ever. Governance checks fire at the repository layer, not the UI layer, so they cannot be bypassed by UI changes. The table survives migrations via `ALTER TABLE ADD COLUMN IF NOT EXISTS` backward compatibility. CSV export is available for every reviewer's decisions.

### Feature 5: Governance Enforcement

| Attribute | Value |
|---|---|
| Status | Complete |
| Files | `db/audit_repository.py:save_decision()` |

Three invariants enforced at the persistence layer (ADR-004):
1. `finding_id` must be non-empty — no anonymous decisions
2. `citation` must be non-None — no uncited decisions
3. `override_reason` must be non-empty when a HIGH finding is overridden

These cannot be circumvented by UI changes because they live in the repository layer.

### Feature 6: SQLite Persistence

| Attribute | Value |
|---|---|
| Status | Complete |
| Files | `db/audit_repository.py:initialize_database()`, `audit.db` |

Single-file SQLite database created at first run. Schema initializes via `CREATE TABLE IF NOT EXISTS`. Backward-compatible migration (`ALTER TABLE ADD COLUMN IF NOT EXISTS citation_effective_date`) handles upgrade from pre-refactor schema without data loss.

### Feature 7: CSV Export

| Attribute | Value |
|---|---|
| Status | Complete |
| Files | `db/audit_repository.py:export_decisions_csv()` |

All audit decisions exportable to CSV string, filterable by `claim_id` and/or `reviewer_name`. Useful for retrospective denial analytics and payer appeals documentation.

### Feature 8: Manual Claim Intake

| Attribute | Value |
|---|---|
| Status | Complete |
| Files | `app/claim_intake.py`, `app/main.py:_render_manual_mode()` |

A full service-line coding grid: CPT code, ICD-10 codes, modifiers, units, place of service, NPI, and payer selector. Supports Add/Remove/Clear service lines and Load Worked Example. `build_manual_claim()` normalizes codes (strip + uppercase), deduplicates, merges all service lines into the flat `ClaimIn` format, and preserves both `payer` (backward compat) and `payer_name`/`payer_id` keys. PHI-guard caption on the notes field.

9 payers in `PAYER_ID_MAP`: Medicare, Medicaid, Blue Cross Blue Shield, Aetna, Cigna, UnitedHealth, Humana, Anthem, and default.

### Feature 9: Policy Intelligence Foundation

| Attribute | Value |
|---|---|
| Status | Partial — interface ready, data synthetic |
| Files | `retrieval/policy_repository.py`, `data/reference/policy_examples.json` |

JSON-backed policy reference service with a ChromaDB-compatible public interface: `find_policy_by_document_id()`, `find_policies_by_codes()`, `get_citation_detail()`. Interface designed as a drop-in replacement for ChromaDB once the RAG pipeline is built (ADR-009). Currently holds 5 synthetic policy examples.

### Feature 10: Test Suite

| Attribute | Value |
|---|---|
| Status | 127 tests passing; `test_orchestrator.py` is a stub; `test_rules.py` has real coverage |
| Files | `tests/test_audit.py`, `tests/test_claim_intake.py`, `tests/test_policy_repository.py`, `tests/test_rule_engine.py`, `tests/test_rules.py`, `tests/test_ncci_loader.py`, `tests/test_orchestrator.py` |

| Test File | Lines | Coverage Focus |
|---|---|---|
| `test_audit.py` | 202 | Audit repository governance, CSV export, schema migration |
| `test_claim_intake.py` | 246 | Payer lookup, NPI format check, code normalization, build_manual_claim |
| `test_policy_repository.py` | 317 | Policy lookup by code, document ID, citation detail |
| `test_rule_engine.py` | 279 | Rule dispatch, finding_id stamping, severity sorting |
| `test_ncci_loader.py` | ~420 | File discovery, xlsx loading, active/deleted filter, bidirectional lookup, file-backed findings, synthetic fallback, real-file integration (44 tests) |
| `test_rules.py` | 19 | NCCI pair detection, code validity rules |
| `test_orchestrator.py` | 15 | Stub — placeholder tests only |

### Feature 11: Architecture Documentation

| Attribute | Value |
|---|---|
| Status | Complete |
| Files | `docs/Architecture_Decisions.md`, `docs/Technical_Debt_Register.md`, `docs/Roadmap.md`, `CLAUDE.md` |

11 ADRs written with context, decision, rationale, tradeoffs, and future replacement points (ADR-011 added for file-backed NCCI PTP lookup with synthetic fallback). 5 deferred decisions documented with explicit triggers. 17 open tech debt items tracked with severity (TD-01 resolved in Sprint 5). 11-phase roadmap with milestone commits.

---

## 4. PRD Traceability Matrix

| PRD Requirement | Priority | Status | Evidence |
|---|---|---|---|
| NCCI PTP bundling check | P0 | Complete | `rules/ncci.py` + `rules/ncci_loader.py`: ~1.73M active pairs from CMS xlsx (v322r0, effective 2026-07-01); synthetic fallback documented |
| MUE limit enforcement | P0 | Not Started | `rules/mue.py` is a stub file |
| NPI validation | P0 | Partial | `app/claim_intake.py:validate_npi()`: 10-digit format only; Luhn not implemented |
| ICD-10-CM code validity | P0 | Partial | `rules/code_validity.py`: 2 hardcoded rules; no reference file loaded |
| HCPCS/CPT code validity | P0 | Partial | Same file; no CPT crosswalk loaded |
| Coverage validation agent (RAG + LLM) | P0 | Not Started | `agents/coverage_validation.py`: docstring only |
| Documentation review agent | P0 | Not Started | `agents/documentation_review.py`: docstring only |
| Denial prevention synthesis | P0 | Not Started | `agents/denial_prevention.py`: docstring only |
| Orchestrator (parallel agents) | P0 | Not Started | `agents/orchestrator.py`: docstring only |
| Human-in-loop decision | P0 | Complete | `app/main.py` findings panel + Approve/Deny/Escalate |
| Override reason enforcement | P0 | Complete | `db/audit_repository.py:save_decision()` governance checks |
| Append-only audit trail | P0 | Complete | SQLite INSERT-only; no UPDATE/DELETE paths |
| Citation requirement (every finding) | P0 | Complete (rule layer) | `Citation` dataclass; `save_decision()` requires citation |
| Citation: document_id | P0 | Complete (rule layer) | `Citation.doc_id` in every finding |
| Citation: section | P0 | Complete (rule layer) | `Citation.section` in every finding |
| Citation: effective_date | P0 | Complete (rule layer) | `Citation.effective_date` in audit schema |
| LCD/NCD retrieval (CMS Coverage API) | P0 | Not Started | `retrieval/ingest.py`, `retrieval/vector_store.py`: stubs |
| ChromaDB vector store | P0 | Not Started | `retrieval/vector_store.py`: stub |
| Manual claim intake | P0 | Complete | `app/claim_intake.py` + service-line grid in `app/main.py` |
| ≥90% finding precision | P0 | Not Measurable | No golden set; no agent layer |
| ≥85% recall | P0 | Not Measurable | No golden set; no agent layer |
| 100% citation coverage | P0 | Enforced | Governance rejects uncited findings at `save_decision()` |
| <30s per review latency | P0 | Partial (rule layer only) | Rule layer is synchronous; LLM latency untested |
| Batch CSV upload | P1 | Not Started | TD-07a; no batch mode |
| Payer-specific rules | P1 | Not Started | `PAYER_ID_MAP` exists; no payer rule differentiation |
| CARC analytics | P1 | Not Started | No CARC codes in any model |
| Commercial payer policies | P2 | Not Started | Only CMS sources planned |
| No PHI constraint | Requirement | Complete | PHI-guard caption; synthetic data only |
| Synthetic data only | Requirement | Complete | No real claims in codebase or data files |

**Summary:** 14 of 28 tracked requirements are Complete (NCCI PTP bundling check promoted from Partial to Complete in Sprint 5). 10 partially implemented. 10 Not Started. 4 Not Measurable (require the agent/eval layer).

---

## 5. Remaining Gaps

### Gap 1: Deterministic Layer Completion (Phase 3 — NCCI complete, remainder pending)

NCCI PTP edits are now real (Sprint 5). The remaining deterministic layer gaps are:

- **MUE tables:** `rules/mue.py` is entirely a stub. Need MUE lookup with MAI-aware severity (MAI-1 = absolute limit, MAI-2 = per-claim, MAI-3 = per-date-of-service).
- **NPI validation:** `validate_npi()` checks 10-digit format only. Luhn check-digit algorithm must be added (PRD P0 requirement).
- **ICD-10-CM and CPT reference files:** `rules/code_validity.py` has 2 hardcoded rules. Need FY2026 ICD-10-CM reference data and CPT crosswalk loaded from `data/reference/`.

### Gap 2: LCD/NCD Retrieval Pipeline (Phase 4)

The coverage validation agent requires a working RAG layer. All three retrieval modules are stubs:
- `retrieval/ingest.py` — CMS Coverage API client
- `retrieval/chunking.py` — section-aware LCD/NCD splitter
- `retrieval/vector_store.py` — ChromaDB interface

`retrieval/policy_repository.py` has the right public interface and 5 synthetic examples, designed for ChromaDB backend swap without changing the agent interface (ADR-009).

### Gap 3: Coverage Validation Agent (Phase 5)

`agents/coverage_validation.py` is a docstring. This is the most complex agent: query vector store with dx/procedure pair → call Claude Sonnet 4.6 via structured tool use → synthesize findings with mandatory citations from retrieved LCD/NCD text. No finding without a retrieved source.

### Gap 4: Documentation Review Agent (Phase 6)

`agents/documentation_review.py` is a docstring. Analyzes clinical note text for E/M level support and code specificity. Lighter reasoning than coverage validation; requires `note_text` field from `ClaimIn`.

### Gap 5: Orchestrator + Denial Prevention Agent (Phase 7)

`agents/orchestrator.py` and `agents/denial_prevention.py` are docstrings. The orchestrator dispatches the rule layer first, then runs agents in parallel. `denial_prevention.py` synthesizes all findings into a `RiskAssessment` deterministically — the only agent with no LLM call.

The `RiskAssessment` Pydantic model in `db/schema.py` is a stub (DEFER-003). The orchestrator multi-table audit schema is deferred (DEFER-004).

### Gap 6: Evaluation Framework (Phase 8)

No golden set exists. `tests/test_rules.py` and `tests/test_orchestrator.py` are stubs. The PRD requires ≥90% precision and ≥85% recall — these targets cannot be measured until the agent layer exists and a labeled claim corpus is created.

### Gap 7: Deployment (Phases 9–10)

No deployment exists. Requirements: `ANTHROPIC_API_KEY` in `.env` (not yet guarded at startup — TD-12), ChromaDB (in requirements.txt but not active), CMS reference data in `data/reference/` (git-excluded), Streamlit Cloud or equivalent hosting.

### Gap 8: UI Component Layer

`app/components/` contains three stub modules: `findings_panel.py`, `claim_form.py`, `audit_view.py`. All rendering lives in `app/main.py` (~570 lines). Extracting components will matter when agent findings need richer display (TD-13).

---

## 6. Technical Debt Assessment

Full register: `docs/Technical_Debt_Register.md`

### HIGH Severity — Blocks PRD Completeness

| ID | Item | Location | Impact |
|---|---|---|---|
| ~~TD-01~~ | ~~Only 1 NCCI PTP edit pair~~ | ~~`rules/ncci.py`~~ | **RESOLVED Sprint 5** — file-backed loader with ~1.73M pairs (CMS v322r0) |
| TD-02 | MUE module is entirely a stub | `rules/mue.py` | No MUE enforcement at all |
| TD-03 | NPI validation is format-only (no Luhn check) | `app/claim_intake.py:validate_npi()` | Invalid NPIs pass validation |
| TD-04 | All LLM agents are stubs | `agents/` (all files) | No AI-generated findings; no coverage or documentation review |
| TD-05 | RAG retrieval pipeline not built | `retrieval/` (ingest, chunking, vector_store) | Coverage agent cannot retrieve LCD/NCD policy text |
| TD-06 | Only 2 hardcoded code validity rules | `rules/code_validity.py` | Most dx/procedure conflicts and modifier errors not caught |

### MEDIUM Severity — Affects Reliability and Testability

| ID | Item | Location | Impact |
|---|---|---|---|
| TD-07a | CSV batch upload not implemented | No file | Only one claim at a time; PRD P1 batch mode missing |
| TD-07b | NPI Luhn check not in validate_npi() | `app/claim_intake.py` | Synthetic NPIs (e.g. 1234567890) pass; real invalid NPIs pass |
| TD-08 | test_rules.py and test_orchestrator.py are stubs | `tests/` | 2 of 6 test files are placeholders |
| TD-09 | Golden set evaluation not implemented | No file | PRD accuracy targets cannot be measured |
| TD-10 | db/audit.py coexists with audit_repository.py | `db/` | Two audit modules; `audit.py` is legacy |
| TD-11 | ClaimIn fields typed as bare `list` | `rules/models.py` | `cpt_codes: list`, `icd10_codes: list` — no element type |
| TD-12 | No ANTHROPIC_API_KEY guard at startup | `app/main.py` | App starts silently; LLM calls will fail late and cryptically |

### LOW Severity — Polish and Traceability

| ID | Item | Location | Impact |
|---|---|---|---|
| TD-13 | app/components/ are all stubs | `app/components/` | `main.py` grows unbounded; rendering logic not extractable |
| TD-14 | requirements.txt lists unused deps (chromadb, pydantic) | `requirements.txt` | Increases install size; pydantic not yet used |
| TD-15 | Citation edition says "synthetic sample" for code validity | `rules/code_validity.py` | NCCI citations now real (v322r0); code_validity citations still hardcoded |
| TD-16 | No application logging | Entire codebase | Debugging production issues requires print statements |
| TD-17 | Synthetic NPIs don't pass Luhn validation | `app/claim_intake.py:WORKED_EXAMPLE` | Demo data will break NPI validation once Luhn is implemented |

**Summary:** 26 tracked items total. 10 resolved (TD-01 resolved Sprint 5). 16 open: 5 HIGH, 7 MEDIUM, 4 LOW.

---

## 7. Readiness Assessment

Scores are 0–100. 100 = production-quality, no gaps for the stated purpose.

### Portfolio Demo Readiness: 54 / 100

**What works:** The app runs. A reviewer can enter a claim, see findings with cited sources (now backed by real CMS NCCI v322r0 data), make a decision, and view an audit trail. The NCCI finding now shows the actual CMS source file (ccipra-v322r0-f4.xlsx), version (v322r0), and effective date (2026-07-01). The governance story (citation-required, append-only audit, override enforcement) is compelling and demonstrable.

**What's missing:** LLM agents shown in the architecture diagram don't exist. A technical interviewer who probes "show me the coverage agent" finds a docstring. Code validity findings still come from 2 hardcoded rules. The demo is convincing with NCCI findings; the coverage gap remains visible.

**Ceiling:** One working LLM agent with real citations would score 75+.

---

### PM Interview Readiness: 65 / 100

**What works:** The PRD traceability matrix shows clear P0/P1/P2 prioritization. ADRs demonstrate tradeoff reasoning. The Technical Debt Register shows what you're deferring and why. The governance-first decision (audit before agents) shows PM judgment about risk sequencing.

**What's missing:** No metrics. The PRD targets (≥90% precision, ≥85% recall) cannot be discussed with evidence. No user research cited. No payer feedback incorporated. The business case ($57/claim, 86% preventable) is in the PRD but not visible as a tracked success metric.

**Ceiling:** Adding a golden-set evaluation and wiring precision/recall numbers into the README would score 80+.

---

### Director of Engineering Interview Readiness: 65 / 100

**What works:** Architecture decisions are documented with context and tradeoffs (11 ADRs including ADR-011 on NCCI file-backed loading with performance characteristics). The rule-before-LLM constraint is enforced. The append-only audit pattern is production-grade. SHA-256 finding IDs are stable. 127 tests passing, including substantive NCCI loader tests (not stubs). `functools.lru_cache` on `_build_edit_table()` with documented first-load latency (~54s) and test isolation strategy (`_clear_ncci_cache()`) shows production thinking.

**What's missing:** No CI/CD, no deployment story, no secrets management (TD-12), no logging (TD-16). One test file stub remains (`test_orchestrator.py`). The agent layer is entirely absent.

**Ceiling:** Adding CI, secrets guard, and one working agent with evaluation would score 80+.

---

### AI PM Interview Readiness: 60 / 100

**What works:** The RAG architecture is correctly specified (chunking → ChromaDB → LLM reasoning → cited finding). The citation-first constraint ("no citation → no finding") shows understanding of LLM hallucination risk in healthcare. Policy repository interface designed for ChromaDB drop-in replacement — a thoughtful abstraction. The NCCI loader demonstrates data pipeline thinking: dtype handling for integer-stored Excel cells, usecols optimization (5 of 7 columns), active-pair filtering, caching strategy, and graceful fallback — all documented.

**What's missing:** No LLM has been called. The coverage validation agent (the most demanding AI task) doesn't exist. Can't speak to prompt engineering, retrieval quality, or latency from experience. The model choice (claude-sonnet-4-6) is documented but untested.

**Ceiling:** One working RAG-grounded agent with latency numbers would score 80+.

---

### Healthcare AI Governance Readiness: 72 / 100

**What works:** This is the project's strongest dimension. Citation as first-class dataclass (ADR-002) is correct for auditability. Append-only audit (ADR-004) is a compliance-grade pattern. Human-in-loop with mandatory override reasons is the right design for a clinical support tool. "AI does the research. Humans make the call" is the correct framing. No PHI anywhere in the codebase or data files.

**What's missing:** No HIPAA BAA discussion. No data retention policy. No access control on the audit database. No rate limiting or input validation beyond code normalization. The "synthetic data only" constraint is not machine-enforced — a user could type real PHI into the notes field; only the caption warns them.

**Ceiling:** Adding input sanitization and a deployment-level access control story would score 85+.

---

### Startup MVP Readiness: 22 / 100

**What works:** The value proposition is clear and the architecture can scale to the full PRD. The database schema and governance model are production-appropriate. Manual claim intake is real.

**What's missing:** Not deployable. No real validation data. No LLM agents. No evaluation metrics. A paying customer would see 3 findings from hardcoded rules and a stub agent layer. The system cannot deliver on its core promise until Phases 3–7 are complete.

**Ceiling:** Completing Phases 3–5 would yield a deployable MVP scoring 55+.

---

## 8. Competitive Assessment

### vs. Typical PM Portfolio (no code)

**Advantage:** This project has running code, an 83-test suite, a proper database, and documented architecture decisions. Most PM portfolios have a PRD PDF and a Figma mockup. This is categorically stronger — it demonstrates you can ship, not just specify.

**Gap:** Most senior PMs bring metrics and user research. This project has no user interviews, no pilot data, and no business metrics beyond the PRD.

**Verdict:** Top 15% of PM portfolio projects for ambition and execution depth.

---

### vs. AI PM / ML Portfolio (with LLM projects)

**Advantage:** The governance architecture (citation-first, audit trail, human-in-loop) is more sophisticated than the typical "I built a chatbot" AI portfolio entry. Healthcare domain expertise is a real differentiator — NCCI, MUE, LCD/NCD are not general knowledge.

**Gap:** No LLM has been called. An AI PM portfolio that runs RAG pipelines end-to-end or shows precision/recall curves will outperform this project in AI implementation depth. This project's AI layer is entirely documented, not demonstrated.

**Verdict:** Top 30% for architecture and domain sophistication. Middle of the pack for AI implementation until the agent layer ships.

---

### vs. Healthcare AI Portfolio (domain-specific projects)

**Advantage:** The regulatory awareness (NCCI, MUE, NPPES, CMS Coverage API, ICD-10-CM annual cadence, MAI severity levels) is real domain knowledge. The citation requirement reflecting LCD/NCD policy structure shows understanding of how CMS coverage decisions work. Governance-first before AI-first is the right instinct for healthcare.

**Gap:** EHR integration projects with real FHIR data, or payer API projects with real remittance data, carry more weight in healthcare-specific portfolios. This project is pre-data and pre-production.

**Verdict:** Strong healthcare AI portfolio entry once the agent layer and real reference data are added. Currently strongest on architecture and governance; thinner on AI execution.

---

## 9. Recommended Next Milestone

### Phase 3: Complete Deterministic Layer

**Why this is the highest-value next step:**

Every subsequent phase (Coverage Agent, Documentation Agent, Orchestrator, Evaluation) depends on the rule layer being real. If NCCI has 1 pair when demoed, a knowledgeable interviewer will immediately spot it. More critically, the Coverage Validation Agent's findings only add value when the deterministic rules it complements are credible — flagging a bundled pair the rule engine missed undermines trust in the entire system.

Phase 3 is also the most self-contained phase: no LLM, no live APIs beyond NPPES, no ChromaDB. Each rule module can be implemented and tested independently with fully deterministic assertions.

**Dependencies (all satisfied):**
- `rules/ncci.py` swap point documented ✅
- `rules/mue.py` interface designed ✅
- `rules/npi.py` NPI lookup pattern established ✅
- `rules/code_validity.py` swap point documented ✅
- `data/reference/` directory established ✅

**Effort estimate:** 2–3 weeks

| Task | Time |
|---|---|
| NCCI PTP CSV loader (CMS quarterly file) | 1–2 days |
| MUE table loader with MAI severity | 2–3 days |
| NPI Luhn validation + NPPES live check | 1 day |
| ICD-10-CM reference file loader | 2–3 days |
| Expand test_rules.py from stub to real tests | 2 days |

**Impact:**
- 6 HIGH debt items (TD-01 through TD-06, deterministic layer subset) move toward resolved
- Demo becomes: "Here's a claim with a real NCCI bundle conflict that Medicare would deny" — credible
- Unblocks Phase 4 (RAG pipeline) and Phase 5 (Coverage Agent)
- PRD P0 requirements for NCCI, MUE, NPI jump from Partial to Complete

---

## 10. Recommended Development Roadmap

Phases in priority order, reflecting the dependency chain and interview/demo impact at each step.

### Phase 3: Complete Deterministic Layer (2–3 weeks) — DO NEXT

Load real CMS reference data. Implement Luhn NPI validation. Expand test_rules.py from stub to full coverage. End state: every P0 rule is real, not hardcoded.

**Deliverables:** Real NCCI PTP CSV loader; MUE table with MAI severity; Luhn NPI validation; ICD-10-CM reference file; expanded test suite; TD-01, TD-02, TD-03, TD-06 resolved.

---

### Phase 4: LCD/NCD Retrieval Pipeline (2–3 weeks)

Build the RAG foundation. Implement `retrieval/ingest.py` (CMS Coverage API), `retrieval/chunking.py` (section-aware splitting), `retrieval/vector_store.py` (ChromaDB interface). Swap `retrieval/policy_repository.py` from JSON to ChromaDB backend.

**Deliverables:** CMS API client; LCD chunker preserving section boundaries; ChromaDB index with ≥10 real LCD documents; policy_repository.py backend swapped; tests against real retrieved content.

---

### Phase 5: Coverage Validation Agent (3–4 weeks)

First LLM agent. Implement `agents/coverage_validation.py`: query vector store with dx/procedure pair → call Claude Sonnet 4.6 via structured tool use → synthesize cited findings. Enforce: no citation → no finding. Measure latency (PRD target: <30s end-to-end). Add `ANTHROPIC_API_KEY` guard at startup (resolves TD-12).

**Deliverables:** Working RAG-grounded LLM agent; latency measurement; citation suppression enforced; startup API key check.

---

### Phase 6: Documentation Review Agent + Orchestrator (2–3 weeks)

Implement `agents/documentation_review.py` (E/M level support, code specificity from `note_text`). Implement `agents/orchestrator.py` (dispatches rule layer first, then agents in parallel). Implement `agents/denial_prevention.py` (deterministic synthesis of all findings into `RiskAssessment` — no LLM call). Resolve DEFER-003 (RiskAssessment Pydantic model) and DEFER-004 (multi-table audit schema).

**Deliverables:** Three agents running in parallel behind orchestrator; RiskAssessment returned to UI; full end-to-end flow active.

---

### Phase 7: Evaluation Framework (2 weeks)

Build golden set of ≥50 labeled synthetic claims. Implement precision/recall measurement (`pytest -m golden`). Tune thresholds and prompts until ≥90% precision and ≥85% recall. Document findings.

**Deliverables:** Golden set corpus; pytest golden marker; precision/recall numbers in README; TD-09 resolved.

---

### Phases 8–10: Portfolio Publication + Deployment (2 weeks)

Add CI (GitHub Actions: tests + linting). Write README with architecture diagram, demo GIF, and metrics. Extract `app/components/` from `main.py`. Add application logging (TD-16). Deploy to Streamlit Cloud. Make repo public.

**Deliverables:** Public repo; Streamlit Cloud deployment; README with screenshots and precision/recall; CI green.

---

### Full Timeline Summary

| Phase | Focus | Duration | Cumulative |
|---|---|---|---|
| 3 | Real deterministic rules | 2–3 weeks | Week 3 |
| 4 | RAG pipeline | 2–3 weeks | Week 6 |
| 5 | Coverage agent (first LLM) | 3–4 weeks | Week 10 |
| 6 | Docs agent + orchestrator | 2–3 weeks | Week 13 |
| 7 | Evaluation framework | 2 weeks | Week 15 |
| 8–10 | Portfolio + deployment | 2 weeks | Week 17 |

**Conservative estimate to portfolio-ready MVP: 15–17 weeks from today (by ~October 2026).**

---

## 11. Final Verdict

### Is this portfolio-worthy today?

**Yes, with caveats.** The project demonstrates engineering judgment, healthcare domain expertise, and governance sophistication that most PM portfolios lack entirely. The Architecture Decision Records, Technical Debt Register, and Roadmap are signals of professional rigor. The app runs and is demonstrable.

However, the AI layer — the entire point of the project — does not exist yet. A knowledgeable interviewer who digs past the UI will find stubs. The honest framing today is: "I built the governance and rule layer; the LLM agents are the next phase." That is a defensible position if stated directly.

**Minimum threshold for unqualified portfolio use:** Complete Phase 5 (first working LLM agent with real citations). That transforms the narrative from "I designed an AI system" to "I built one."

---

### Is this interview-worthy today?

**Yes, for the right interview.** Best suited for interviews where you want to demonstrate:
- Healthcare RCM domain knowledge (NCCI, MUE, NPI, LCD/NCD, E/M coding)
- AI governance design (citation-first, audit trail, human-in-loop)
- Engineering judgment under constraint (rules-before-LLM, deterministic over generative where possible)
- PM-level thinking (PRD → ADRs → tech debt register → phased roadmap)

Less suited for interviews where the evaluator will probe AI implementation depth (prompt engineering, RAG quality, model evaluation). For those interviews, wait until Phase 5 ships.

**Best use today:** PM interviews, product design discussions, healthcare AI governance conversations.

---

### What is the single most important missing feature?

**The Coverage Validation Agent (`agents/coverage_validation.py`).**

This is the feature that makes the project real. It is:
- The only LLM-backed component in the architecture
- The only feature that addresses the business problem directly (LCD/NCD policy non-compliance is the #1 preventable denial reason by volume)
- The hardest to build (requires RAG pipeline, structured tool use, citation retrieval, hallucination suppression)
- The one thing a demo reviewer cannot overlook when it's absent

Everything else — real NCCI data, Luhn NPI check, golden set evaluation — makes the system more accurate. The Coverage Validation Agent makes it a *different kind of system*: one that does AI-grounded policy research instead of hardcoded rule lookup. Until it exists, the "Copilot" in the product name is aspirational.

Phase 4 (RAG pipeline) is a prerequisite. Phase 3 (real rule data) makes the surrounding context credible. But the Coverage Validation Agent is the milestone that changes the project's category from "well-architected prototype" to "AI system."
