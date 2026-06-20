# Repository Status Report — Denial Prevention Copilot

**Generated:** 2026-06-16
**Sprint:** 10 complete (Option A — Coverage Policy Corpus Expansion, 14 new LCD/NCD entries, 27 retrieval validation tests)
**Branch:** main
**Last commit:** Expand coverage policy corpus: 14 new LCD/NCD entries, 27 retrieval validation tests, 6 demo scenarios

> **Update (Phase 4, Sessions 1A–1D, post-2026-06-16):** This report predates Phase 4. The RAG pipeline described below as "0% built" / "stubs" is now implemented: `retrieval/chunking.py`, `retrieval/vector_store.py`, and `retrieval/ingest.py` are all live (the last verified against real CMS Coverage API responses — see `Technical_Debt_Register.md` TD-18), and `agents/coverage_validation.py` (Session 1D) now queries the ChromaDB vector store first, falling back to the JSON policy corpus described in this report only when the vector store is empty, returns nothing, or raises. The vector store is **not pre-seeded** with a real corpus, so in a fresh checkout the JSON-fallback behavior this report describes is still what actually runs end-to-end — this report's architecture and gap analysis otherwise remains accurate for everything outside Phase 4/5v2. See `docs/Roadmap.md` Phase 4 and `docs/Technical_Debt_Register.md` TD-05 (resolved) / TD-18 (resolved) / TD-19 (new) for current detail rather than the "Gap 2"/"Gap 3" sections below.
>
> **Update (Phase 7, Unified Review, post-2026-06-18):** This report also predates Phase 7. `agents/orchestrator.py` and `agents/denial_prevention.py` are no longer stubs — both are implemented against a deliberately **light** scope: combine the rule layer and the Coverage Validation Agent (the only implemented LLM agent) into one `RiskAssessment`. This report's "Gap 5" and the PRD Traceability Matrix's "Orchestrator (parallel agents)" / "Denial prevention synthesis" rows describing these as "Not Started" are now stale — see `docs/Roadmap.md` Phase 7 and `docs/Technical_Debt_Register.md` TD-04 (partially resolved) for current detail. **Documentation Review Agent remains not implemented** — it is explicitly deferred ("Deferred / Under Evaluation" in the roadmap, not removed from the product vision, to be revisited before public release), and no placeholder finding stands in for it. Coding Validation is not planned as a separate LLM agent at all (see ADR-015) — the rule layer's NCCI/MUE/code_validity checks already cover that ground deterministically. Current MVP scope is: Unified Review (rule layer + Coverage Validation Agent → RiskAssessment) + human-in-the-loop audit. 308 tests passing (up from the 200 referenced below).
>
> **Update (v1.3, Coding Validation Agent, post-2026-06-18):** ADR-015's "Coding Validation is not planned as a separate LLM agent" framing (referenced in the update above) is now superseded — see `docs/Architecture_Decisions.md` ADR-016. `agents/coding_validation.py` is implemented, mirroring the Coverage Validation Agent's architecture and scoped narrowly to coding defensibility judgment the rule layer cannot make (diagnosis specificity, diagnosis-to-procedure support, payer scrutiny risk) — it does not re-implement NCCI/MUE/modifier/code-validity checks. The orchestrator now calls Coverage Validation then Coding Validation sequentially, and `denial_prevention.synthesize()` combines all three finding sources into one `RiskAssessment`. Documentation Review Agent remains the only deferred agent. Current MVP scope is: Unified Review (rule layer + Coverage Validation Agent + Coding Validation Agent → RiskAssessment) + human-in-the-loop audit. 349 tests passing (up from 308).
>
> **Update (v1.4, Golden Set Evaluation Framework, post-2026-06-18):** "Gap 6: Evaluation Framework (Phase 8)" below is now stale. `evaluation/golden_claims.json` (14 labeled synthetic claims), `evaluation/metrics.py`, `evaluation/harness.py`, and `evaluation/run_evaluation.py` implement the golden-set measurement the PRD's ≥90%/≥85% targets require — built as a standalone CLI module rather than a `pytest -m golden` marker (see `docs/Roadmap.md` Phase 8 "Deviation from original plan"). Offline (rule layer only, no API calls): 1.00 precision / 1.00 recall / 1.00 F1. Live (real `claude-haiku-4-5` calls): Rule Engine still 1.00/1.00/1.00; Coverage/Coding Agents 0.30/0.25 precision at 1.00 recall — tracked as `docs/Technical_Debt_Register.md` TD-24 (open). 375 tests passing (up from 349).
>
> **Update (v1.5, ICD-10 Expansion, post-2026-06-19):** The "ICD-10-CM code validity" row in the PRD Traceability Matrix below, and "Gap 1"'s ICD-10-CM bullet, are now stale. `rules/icd10_loader.py` (file-backed parser for the real CMS ICD-10-CM FY2026 order file, ~98,000 codes, gitignored like NCCI/MUE) and `rules/icd10.py` (`check_icd10_validity()` — `icd10_invalid` HIGH finding for codes not in the dataset, `icd10_unspecified` MEDIUM finding for codes whose CMS description contains "unspecified") are now wired into `rules/rule_engine.py`, respecting the existing HIGH-NPI short-circuit. The pre-existing `dx_procedure_conflict`/`missing_modifier_25` rules in `rules/code_validity.py` were left untouched — this is a new, separate check, not a replacement of those two rules. Two golden claims (`GOLD-009`, `GOLD-011`) needed their `expected_findings` updated since their diagnosis codes (`J06.9`, `R10.9`) are themselves unspecified per CMS; Rule Engine offline precision/recall/F1 remains 1.00/1.00/1.00. See `docs/Roadmap.md` Phase 8.5. 404 tests passing (up from 375).
>
> **Update (v1.6, Public Release Hardening, post-2026-06-19):** This sprint did not add product features — it closed the gap between "works on the developer's machine with a real `.env`" and "works correctly on a fresh public clone with no API key." `agents/orchestrator.py:_ai_enabled()` now gates both agents before either is called (closes TD-12); `app/main.py` shows an explicit "⚠ AI Agents Disabled" warning naming `ANTHROPIC_API_KEY` instead of failing silently; three sample claims (`CLM-001`, `CLM-002`, `CLM-005`) show pre-generated, clearly labeled AI findings via `data/synthetic/cached_ai_demo_artifacts.json` when no key is present, so the AI layer is previewable without a live call; `agents/run_logger.py` adds local structured logging for each orchestrator-dispatched check (partially closes TD-16). A repository-wide hygiene pass removed interview/recruiter/hiring-manager/UiPath framing and a personal-name byline from authored docs (the original PRD PDF's two UiPath press-release citation URLs were left as-is — it's the unmodified source spec, not authored prose). `README.md` was rewritten with portfolio/demo framing, a "not for clinical or billing use" disclosure, and an Architecture Overview section. See `docs/Roadmap.md` Phase 8.6 and `docs/Technical_Debt_Register.md` (TD-12 closed, TD-16 partial). 426 tests passing (up from 404). The readiness scores in Section 7 below predate this sprint and were not revised — this sprint's scope was release-safety, not the underlying feature maturity those scores measure.
>
> **Update (v1.7, Quality Hardening Sprint, post-2026-06-19):** A small, deliberately scoped set of TD items closed without growing the agent count, building a full HCPCS reference-file platform, or touching UI/deployment. The "TD-06 | Only 2 hardcoded code validity rules" row below (Section 6) and the "ICD-10-CM code validity"-adjacent gaps are now stale: `rules/hcpcs.py` adds a curated ~16-code HCPCS Level II format-recognition check (not a full file-backed loader — see TD-06), and `rules/code_validity.py` gained two new modifier rules (`missing_modifier_76` repeat-procedure, `missing_modifier_50` bilateral), bringing total active modifier rules to 3. The "TD-15 | Citation edition says 'synthetic sample'" row is resolved: `code_validity.py`'s citation `edition` strings now read `"(curated interpretive rule — not file-backed)"`. TD-20 (citation excerpts never persisted) is resolved: `db/audit_repository.py` gained a `citation_excerpt` column via a backward-compatible migration, threaded through to `app/main.py`'s Save Decision handler. TD-24's Phase 1 (golden-set label review, not yet a live re-run) relabeled `GOLD-008`/`GOLD-009` as legitimate agent-positive claims and added `GOLD-015` as an explicit agent-negative baseline — Coverage/Coding Agent live precision was not re-measured this sprint. TD-27 gained a backend-only real-data-vs-synthetic-fallback status check (`rules/data_source_status.py`); no UI indicator was added, by design. See `docs/Roadmap.md` Phase 8.7 and `docs/Technical_Debt_Register.md` for full detail. 465 tests passing (up from 426). The readiness scores in Section 7 below predate this sprint and were not revised — this sprint closed a handful of TD items, not the broader feature-maturity gaps (ChromaDB pre-seeding, Documentation Review Agent, deployment) those scores measure.

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

The Denial Prevention Copilot is a **well-architected early prototype** with a complete structural skeleton, a fully operational governance/audit layer, three production-grade rule engines backed by real CMS reference data, and the first operational LLM agent. The project has completed Phase A + B of Phase 3, Sprint 8 (UI/UX hardening), Sprint 9 (Coverage Validation Agent v1), and Sprint 10 (Option A — coverage policy corpus expansion). The application runs end-to-end — a claim goes in, deterministic rules fire against real CMS NCCI edits and MUE table, and NPI validates via Luhn + NPPES. The AI Coverage Analysis button invokes Claude via structured tool use to evaluate coverage against retrieved LCD/NCD policy documents, producing cited medical necessity findings. Sprint 10 expanded the LCD/NCD corpus from 4 entries to 18, covering diabetes management, dyslipidemia, lab medical necessity, HbA1c frequency, preventive services, AWV, colonoscopy screening, mammography, observation status, diagnosis specificity, chronic care management, and E/M level documentation — enabling 6 full demo scenarios. The RAG pipeline (ChromaDB, CMS Coverage API) remains deferred, but the JSON policy corpus now covers the most common Medicare denial categories.

### MVP Completion: ~60–65%

The project has strong bones and the first real meat. The scaffolding is production-quality; NCCI bundling detection is now genuine (~1.73M real CMS pairs). The Coverage Validation Agent v1 is live with an 18-entry LCD/NCD corpus. The governance and audit infrastructure is complete; one agent is implemented, three remain stubs, and the RAG pipeline is ~0% built but the policy corpus is richer and 6 demo scenarios are validated end-to-end.

### Strengths

- **Governance-first design:** Citation as a first-class dataclass, SHA-256 finding IDs, append-only SQLite, human-in-loop enforcement — these are production-grade governance patterns built before any LLM exists. This is architecturally rare and directly addresses the PRD governance controls requirement (P0).
- **Clean separation of concerns:** Rule layer → orchestrator → agents → denial prevention is enforced at every level. `rule_engine.py` calls no LLM; `agents/` calls no DB. This modularity makes each layer independently testable and replaceable.
- **Decision record discipline:** 11 Architecture Decision Records written (ADR-011 added for file-backed NCCI), deferral triggers documented, future replacement points mapped. This is unusually rigorous for a prototype.
- **227 tests, all passing:** Tests now cover NPI validation (13 tests, all mocked), NCCI loader (44 tests), MUE loader + rule (35 tests), rule engine (23 tests, including 3 new CHECKS_RUN metadata tests + NPI short-circuit verification), audit governance, claim intake (including units propagation), policy repository (47 tests, including 27 new retrieval validation tests and 6 demo scenario retrievals added in Sprint 10), and coverage validation agent (14 tests, all mocked — no real API calls). `tests/test_rules.py` has 48 tests (was a stub).
- **Real NCCI PTP edits:** Sprint 5 replaced the 1-pair hardcoded lookup with a file-backed loader reading CMS quarterly xlsx files. ~1.73 million active edit pairs across 4 files (ccipra-v322r0-f1 through f4). Modifier 0/1/9 semantics handled. Bidirectional lookup. `functools.lru_cache` for process-lifetime performance. Synthetic fallback when CMS files absent.
- **MUE ingestion (Sprint 6):** `rules/mue_loader.py` + `rules/mue.py` implement file-backed MUE lookup from `data/reference/mue/` with column-name discovery, `lru_cache`, and synthetic fallback. MAI-aware severity: MAI=1 → HIGH, MAI=2/3 → MEDIUM. Wired into rule engine after NCCI.
- **Units field support (Sprint 6):** `build_manual_claim()` now populates `ClaimIn.units` (CPT → unit count) from the service-line grid. UI grid has a Units column. `WORKED_EXAMPLE` updated to include units per service line. MUE check uses this field.
- **NPI validation (Sprint 7):** `rules/npi.py` implements `luhn_valid()` (Luhn check with "80840" prefix per CMS specification), `lookup_nppes()` (NPPES REST API v2.1, 2-second timeout), and `check_npi()`. NPI runs first in the rule engine; HIGH finding (bad format or Luhn failure) short-circuits NCCI/MUE/code_validity. NPPES not found → MEDIUM. NPPES timeout → no finding (review never blocked). Sample claim NPIs blanked to avoid demo noise. 13 new NPI tests (all mocked — no real network calls). `NPPES_NPI_REGISTRY` citation anchor added to `policy_examples.json`.
- **Manual claim intake:** Sprint 4 added a full service-line coding grid (CPT, ICD-10, modifiers, units, POS, NPI, payer) with a worked example, deduplication, and PHI-guard caption. Sprint 6 added the Units column.

### Key Gaps

- **Three PRD agents still stubs** — `agents/coding_validation.py`, `agents/documentation_review.py`, `agents/denial_prevention.py`, and `agents/orchestrator.py` contain only docstrings. `agents/coverage_validation.py` is now implemented (Sprint 9).
- **Rule data mostly synthetic** — NCCI is now real (~1.73M pairs). Code validity still has 2 hardcoded rules. MUE real (Q3 2026 file). NPI now validates via Luhn + NPPES live lookup.
- **RAG pipeline not built** — `retrieval/chunking.py`, `retrieval/ingest.py`, `retrieval/vector_store.py` are empty modules. Coverage agent v1 uses the JSON policy repository as a substitute; ChromaDB upgrade is deferred.
- **Accuracy unverifiable** — The PRD targets ≥90% precision and ≥85% recall. With only one agent and no golden set, these cannot be evaluated.

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

  app/components/             findings_panel, claim_form, audit_view [STUB]
```

### Component Responsibilities (Implemented)

| Component | File | Status | Responsibility |
|---|---|---|---|
| UI (two modes) | `app/main.py` | Active | Streamlit app: sample mode + manual claim entry, findings display, human decision panel |
| Claim intake | `app/claim_intake.py` | Active | Build `ClaimIn` from service-line grid; payer lookup; NPI format check; code normalization |
| Rule engine | `rules/rule_engine.py` | Active | Dispatch to all rule modules; stamp SHA-256 finding_id; sort HIGH→MEDIUM→LOW; exports `CHECKS_RUN` list consumed by UI |
| NCCI PTP check | `rules/ncci.py`, `rules/ncci_loader.py` | Active | File-backed loader; ~1.73M active pairs from CMS xlsx (v322r0); synthetic fallback when files absent |
| MUE check | `rules/mue.py`, `rules/mue_loader.py` | Active | File-backed loader; Q3 2026 CMS Practitioner file; MAI-aware severity; synthetic fallback |
| NPI validation | `rules/npi.py` | Active | Luhn check + NPPES live lookup; HIGH short-circuits engine; MEDIUM for not-found; timeout silenced |
| Code validity | `rules/code_validity.py` | Partial | 2 hardcoded rules (Z00.00 + problem E/M conflict; missing modifier 25) |
| Shared models | `rules/models.py` | Active | `ClaimIn`, `Citation`, `Finding` dataclasses |
| Audit repository | `db/audit_repository.py` | Active | `AuditDecision` dataclass; append-only SQLite; governance enforcement at save |
| Policy repository | `retrieval/policy_repository.py` | Partial | JSON-backed policy lookup; ChromaDB-compatible public interface; 8 entries (5 original + 3 new LCD entries for coverage agent v1) |
| Coverage validation agent | `agents/coverage_validation.py` | Active (v1) | `validate_coverage(claim)`: retrieves LCD/NCD policies from JSON repo, calls Claude via structured tool use (two-tool schema), enforces citation grounding, returns 0 or 1 Finding |

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
| Status | Partial — interface ready; 25 entries total (18 LCD/NCD) covering 14 common Medicare denial categories |
| Files | `retrieval/policy_repository.py`, `data/reference/policy_examples.json` |

JSON-backed policy reference service with a ChromaDB-compatible public interface: `find_policy_by_document_id()`, `find_policies_by_codes()`, `get_citation_detail()`. Interface designed as a drop-in replacement for ChromaDB once the RAG pipeline is built (ADR-009). Sprint 9 added 3 LCD-style entries; Sprint 10 (Option A) added 14 more, bringing the LCD/NCD corpus to 18 entries across these categories:

| Category | document_id | Codes Indexed |
|---|---|---|
| Diabetes management | LCD_DIABETES_MGMT_E11 | E11.9, E11.65, E11.40, E11.329, E13.9 |
| Dyslipidemia management | LCD_DYSLIPIDEMIA_MGMT_E78 | E78.5, E78.00, E78.01, E78.2, E78.4 |
| Metabolic panel medical necessity | LCD_LAB_MEDICAL_NECESSITY_METABOLIC | 80053, 80048, 80076 |
| Lipid panel frequency | LCD_LIPID_PANEL_FREQUENCY | 80061, 82465, 83721 |
| HbA1c frequency | LCD_HEMOGLOBIN_A1C_FREQUENCY | 83036, 83037 |
| Preventive visit 40–64 | LCD_PREVENTIVE_99396_COVERAGE | 99396, Z00.00, Z00.01 |
| Annual Wellness Visit | NCD_AWV_G0438_G0439 | G0438, G0439, Z00.00 |
| Screening colonoscopy | NCD_COLORECTAL_SCREENING_COLONOSCOPY | 45378, 45380, 45385, 45386, 45388 |
| Colonoscopy diagnosis | LCD_COLONOSCOPY_DIAGNOSIS_Z12 | Z12.11, Z12.12, Z80.0, Z83.71 |
| Mammography | NCD_MAMMOGRAPHY_COVERAGE | 77067, 77065, 77066, Z12.31, Z12.39 |
| Observation status | LCD_OBSERVATION_STATUS_BILLING | 99234, 99235, 99236, G0379 |
| Diagnosis specificity | LCD_DIAGNOSIS_SPECIFICITY_REQ | M54.9, M79.3, M25.50, R51.9, R05.9 |
| Chronic care management | LCD_CHRONIC_CARE_MANAGEMENT | 99490, 99491, G0511 |
| E/M level documentation | LCD_EM_CODING_LEVEL_SUPPORT | 99213, 99214, 99215, 99202–99205 |

The six validated demo scenarios (each tested in `tests/test_policy_repository.py`) are:
1. Labs with well-visit dx only: 80053 + 83036 + Z00.00 → `LCD_LAB_MEDICAL_NECESSITY_METABOLIC` + `LCD_HEMOGLOBIN_A1C_FREQUENCY`
2. Diabetes management E/M: E11.9 + 99214 → `LCD_DIABETES_MGMT_E11` (no concern expected)
3. Screening colonoscopy with polypectomy: 45385 + Z12.11 → both colonoscopy policies (conversion concern)
4. Unspecified diagnosis + high-level E/M: M54.9 + 99215 → `LCD_DIAGNOSIS_SPECIFICITY_REQ` + `LCD_EM_CODING_LEVEL_SUPPORT`
5. AWV same-day E/M: G0439 + 99213 + Z00.00 → `NCD_AWV_G0438_G0439` (modifier 25 concern)
6. HbA1c for established diabetic: 83036 + E11.65 → `LCD_HEMOGLOBIN_A1C_FREQUENCY` + `LCD_DIABETES_MGMT_E11` (no concern)

### Feature 10: Coverage Validation Agent v1

| Attribute | Value |
|---|---|
| Status | Active (v1 — JSON-backed retrieval, no ChromaDB) |
| Files | `agents/coverage_validation.py`, `tests/test_coverage_validation.py` |

`validate_coverage(claim: ClaimIn) -> list[Finding]` is the first production LLM integration in the codebase. Governance rules enforced:
- No API key → return [] (checked at call time via `os.getenv`)
- No retrieved LCD/NCD policy → return [] (checked before model call)
- One model call per invocation (`tool_choice={"type": "any"}` forces tool use)
- Model must call a tool; otherwise → return []
- `citation_doc_id` not in retrieved set → suppress finding (hallucination grounding)
- Model exception → return [] (no propagation)

Two-tool schema: `report_coverage_finding` (issue, recommendation, severity, confidence, citation fields) and `no_coverage_concern` (reason). UI: "🤖 Run AI Coverage Analysis" button appears after rule review when `ANTHROPIC_API_KEY` is set. Sidebar shows AI enabled/disabled status. AI findings use the same `_finding_card` component and the same audit trail as rule findings.

**Production validation results (2026-06-18):**

| Metric | Result |
|---|---|
| Status | Production Validated |
| Model | `claude-sonnet-4-5-20250929` |
| Demo scenario | Labs + well-visit dx (CPT 80053 + 83036, ICD-10 Z00.00) |
| Policies retrieved | 7 |
| Policies sent to model | 3 (capped by `_MAX_POLICIES`) |
| Finding generated | Yes — HIGH severity |
| Citation grounding | Passed (`LCD_E_M_MEDICAL_NECESSITY_Z00` in retrieved set) |
| End-to-end latency | 7.27s |
| Errors | None |

### Feature 11: Test Suite

| Attribute | Value |
|---|---|
| Status | 200 tests passing; `test_orchestrator.py` is a stub; `test_rules.py` has real coverage |
| Files | `tests/test_audit.py`, `tests/test_claim_intake.py`, `tests/test_policy_repository.py`, `tests/test_rule_engine.py`, `tests/test_rules.py`, `tests/test_ncci_loader.py`, `tests/test_orchestrator.py`, `tests/test_coverage_validation.py` |

| Test File | Lines | Coverage Focus |
|---|---|---|
| `test_audit.py` | 202 | Audit repository governance, CSV export, schema migration |
| `test_claim_intake.py` | 246 | Payer lookup, NPI format check, code normalization, build_manual_claim |
| `test_policy_repository.py` | ~530 | Policy lookup by code, document ID, citation detail; corpus expansion coverage (47 tests: 20 original + 27 new in Sprint 10) |
| `test_rule_engine.py` | ~310 | Rule dispatch, finding_id stamping, severity sorting, CHECKS_RUN structure + coverage, NPI short-circuit behavior (23 tests) |
| `test_ncci_loader.py` | ~420 | File discovery, xlsx loading, active/deleted filter, bidirectional lookup, file-backed findings, synthetic fallback, real-file integration (44 tests) |
| `test_rules.py` | ~550 | NCCI pair detection, code validity, MUE (35 tests), NPI (13 tests — all mocked) |
| `test_coverage_validation.py` | ~200 | Coverage agent: pre-flight guards (no API key, no policy), tool-use response parsing, citation grounding, hallucination suppression, exception handling, stable finding_id (14 tests — all mocked) |
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
| MUE limit enforcement | P0 | Complete (synthetic fallback) | `rules/mue_loader.py` + `rules/mue.py`: file-backed loader; MAI-aware severity; synthetic fallback; CMS file needed in `data/reference/mue/` for authoritative limits |
| NPI validation | P0 | Complete | `rules/npi.py`: Luhn check + NPPES live lookup; HIGH/MEDIUM/no-finding paths; short-circuit on HIGH; NPPES timeout silenced |
| ICD-10-CM code validity | P0 | Complete (v1.5) | `rules/icd10_loader.py` + `rules/icd10.py`: real CMS FY2026 order file (~98,000 codes); invalid-code (HIGH) and unspecified-diagnosis (MEDIUM) findings; synthetic fallback. `rules/code_validity.py`'s 2 hardcoded dx-procedure/modifier-25 rules are unchanged and unrelated. |
| HCPCS/CPT code validity | P0 | Partial | Same file; no CPT crosswalk loaded |
| Coverage validation agent (RAG + LLM) | P0 | Partial (v1+) | `agents/coverage_validation.py`: implemented; JSON-backed retrieval (18 LCD/NCD entries after Sprint 10); structured tool use; citation grounding enforced; 6 demo scenarios validated; ChromaDB RAG upgrade deferred |
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

**Summary:** 16 of 28 tracked requirements are Complete (NPI validation promoted from Partial to Complete in Sprint 7; MUE promoted in Sprint 6). Coverage agent is Partial (Sprint 9 v1 + Sprint 10 Option A — JSON-backed retrieval, 18 LCD/NCD entries, 6 demo scenarios validated). 8 partially implemented. 8 Not Started. 4 Not Measurable (require the agent/eval layer).

---

## 5. Remaining Gaps

### Gap 1: Deterministic Layer Completion (Phase 3 — NCCI complete, remainder pending)

NCCI PTP edits are now real (Sprint 5). The remaining deterministic layer gaps are:

- **MUE tables:** ✅ Implemented in Sprint 6. `rules/mue_loader.py` + `rules/mue.py`. File-backed with synthetic fallback. CMS MUE Practitioner file needed in `data/reference/mue/` for authoritative limits.
- **NPI validation:** ✅ Complete in Sprint 7. `rules/npi.py` with Luhn check and NPPES live lookup.
- **ICD-10-CM reference file:** ✅ Implemented in v1.5. `rules/icd10_loader.py` + `rules/icd10.py`, backed by the real CMS FY2026 ICD-10-CM order file in `data/reference/icd10/`. `rules/code_validity.py`'s 2 hardcoded dx-procedure/modifier-25 rules remain as-is (separate concern).
- **CPT reference file:** Still pending — no CPT crosswalk loaded from `data/reference/`.

### Gap 2: LCD/NCD Retrieval Pipeline — ChromaDB (Phase 4)

The coverage validation agent v1 uses the JSON policy repository (18 LCD/NCD entries after Sprint 10) as a retrieval substitute. The full ChromaDB RAG pipeline is not yet built:

The coverage validation agent requires a working RAG layer for real CMS LCD/NCD text. All three retrieval modules are stubs:
- `retrieval/ingest.py` — CMS Coverage API client
- `retrieval/chunking.py` — section-aware LCD/NCD splitter
- `retrieval/vector_store.py` — ChromaDB interface

`retrieval/policy_repository.py` has the right public interface and 25 curated entries (18 LCD/NCD), designed for ChromaDB backend swap without changing the agent interface (ADR-009). Sprint 10 (Option A) significantly improved coverage: the agent now retrieves relevant policies for all six validated demo scenarios, covering diabetes, dyslipidemia, lab necessity, HbA1c, preventive services, AWV, colonoscopy, mammography, observation, diagnosis specificity, CCM, and E/M level documentation.

### Gap 3: Coverage Validation Agent — v2 ChromaDB Upgrade (Phase 5 v2)

`agents/coverage_validation.py` is implemented (Sprint 9 — v1). The v1 uses the JSON policy repository for retrieval (18 LCD/NCD entries after Sprint 10) and calls Claude via structured tool use with citation grounding enforced. The remaining gap is the ChromaDB RAG upgrade: replace JSON retrieval with `retrieval/vector_store.py` queries against real CMS LCD/NCD documents. The public interface (`validate_coverage(claim: ClaimIn)`) is unchanged; only `find_policies_by_codes()` call is replaced.

### Gap 4: Documentation Review Agent (Phase 6)

`agents/documentation_review.py` is a docstring. Analyzes clinical note text for E/M level support and code specificity. Lighter reasoning than coverage validation; requires `note_text` field from `ClaimIn`.

### Gap 5: Orchestrator + Denial Prevention Agent (Phase 7)

`agents/orchestrator.py` and `agents/denial_prevention.py` are docstrings. The orchestrator dispatches the rule layer first, then runs agents in parallel. `denial_prevention.py` synthesizes all findings into a `RiskAssessment` deterministically — the only agent with no LLM call.

The `RiskAssessment` Pydantic model in `db/schema.py` is a stub (DEFER-003). The orchestrator multi-table audit schema is deferred (DEFER-004).

### Gap 6: Evaluation Framework (Phase 8) — ✅ Resolved in v1.4

`evaluation/golden_claims.json` (14 labeled claims), `evaluation/metrics.py`, `evaluation/harness.py`, `evaluation/run_evaluation.py` measure precision/recall/F1 against the PRD's ≥90%/≥85% targets. Offline (rule layer): 1.00/1.00/1.00. Live (agent layer): 0.30/0.25 precision at 1.00 recall — open as TD-24, not a harness gap. See `docs/Roadmap.md` Phase 8.

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
| ~~TD-02~~ | ~~MUE module is entirely a stub~~ | ~~`rules/mue.py`~~ | **RESOLVED Sprint 6** — `mue_loader.py` + `mue.py`; file-backed; MAI-aware severity; 35 tests |
| ~~TD-03~~ | ~~NPI validation is format-only (no Luhn check)~~ | ~~`app/claim_intake.py:validate_npi()`~~ | **RESOLVED Sprint 7** — `rules/npi.py:luhn_valid()` + NPPES lookup |
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

**Summary:** 26 tracked items total. 12 resolved (TD-02 resolved Sprint 6; TD-08 partially resolved). 15 open: 4 HIGH (TD-03–TD-06), 6 MEDIUM (TD-07a, TD-07b, TD-08 remainder, TD-09–TD-12), 5 LOW (TD-13–TD-17). (See `docs/Technical_Debt_Register.md` for full detail.)

---

## 7. Readiness Assessment

Scores are 0–100. 100 = production-quality, no gaps for the stated purpose.

### Portfolio Demo Readiness: 55 / 100

**What works:** The app runs end-to-end with two claim modes. The NCCI finding now cites the actual CMS source file (ccipra-v322r0-f4.xlsx), version (v322r0), and effective date (2026-07-01) — this is fully verifiable and distinguishes the project from one using made-up citations. The governance story (citation-required, append-only audit, override enforcement with mandatory reason) is compact and compelling. Manual claim intake lets the demo use any coding scenario, not just 5 fixed examples.

**What's missing:** All LLM agents are stubs. A technical reviewer who asks "show me the coverage agent" finds a docstring. Code validity findings come from 2 hardcoded rules, not a reference file. No RAG pipeline. The worked example produces exactly 3 findings every time — reviewers who dig deeper will notice there's no adaptive behavior.

**Ceiling:** One working LLM agent with a real LCD citation would score 75+. The governance and NCCI story can carry the demo for 2-3 minutes; the stub layer becomes visible under deeper probing.

---

### PM Portfolio Readiness: 67 / 100

**What works:** The PRD traceability matrix maps 25+ requirements to P0/P1/P2 and tracks completion state per sprint. 11 ADRs document context, tradeoffs, and explicit deferral triggers. The Technical Debt Register explains why each item is deferred, not just that it is. The governance-first sequencing (audit before agents) shows PM judgment about risk ordering. NCCI completion demonstrates iterative delivery against a roadmap — Phase 3 is visibly in progress, not stalled.

**What's missing:** No tracked metrics. The PRD targets (≥90% precision, ≥85% recall) cannot be discussed with evidence. No user research cited. No payer feedback incorporated. The business case ($57/claim, 86% preventable) is stated in the PRD but not carried as a tracked success criterion anywhere in the project.

**Ceiling:** One golden-set evaluation with measured precision/recall would score 80+. The documentation rigor is already at 80+; the metrics gap is what caps this score.

---

### Engineering Portfolio Readiness: 65 / 100

**What works:** Architecture decisions are documented with context and tradeoffs (11 ADRs including ADR-011 on NCCI file-backed loading with performance characteristics). The rule-before-LLM constraint is enforced. The append-only audit pattern is production-grade. SHA-256 finding IDs are stable. 127 tests passing, including substantive NCCI loader tests (not stubs). `functools.lru_cache` on `_build_edit_table()` with documented first-load latency (~54s) and test isolation strategy (`_clear_ncci_cache()`) shows production thinking.

**What's missing:** No CI/CD, no deployment story, no secrets management (TD-12), no logging (TD-16). One test file stub remains (`test_orchestrator.py`). The agent layer is entirely absent.

**Ceiling:** Adding CI, secrets guard, and one working agent with evaluation would score 80+.

---

### AI PM Portfolio Readiness: 60 / 100

**What works:** The RAG architecture is correctly specified (chunking → ChromaDB → LLM reasoning → cited finding). The citation-first constraint ("no citation → no finding") shows understanding of LLM hallucination risk in healthcare. Policy repository interface designed for ChromaDB drop-in replacement — a thoughtful abstraction. The NCCI loader demonstrates data pipeline thinking: dtype handling for integer-stored Excel cells, usecols optimization (5 of 7 columns), active-pair filtering, caching strategy, and graceful fallback — all documented.

**What's missing:** No LLM has been called. The coverage validation agent (the most demanding AI task) doesn't exist. Can't speak to prompt engineering, retrieval quality, or latency from experience. The model choice (claude-sonnet-4-6) is documented but untested.

**Ceiling:** One working RAG-grounded agent with latency numbers would score 80+.

---

### Healthcare AI Governance Readiness: 73 / 100

**What works:** This is the project's strongest dimension. Citation as first-class dataclass (ADR-002) is correct for auditability — every finding carries `doc_id`, `section`, `edition`, and `effective_date` that map 1:1 to audit schema columns. The NCCI citation now references the exact CMS file edition (v322r0, 2026-07-01), making the governance claim traceable to a real policy snapshot. Append-only audit (ADR-004) is a compliance-grade pattern. Human-in-loop with mandatory override reasons is the right design for a clinical support tool. No PHI anywhere in the codebase or data files.

**What's missing:** No HIPAA BAA discussion. No data retention policy. No access control on the audit database. No input sanitization beyond a caption warning — a user could type real PHI into the notes field. The "synthetic data only" constraint is not machine-enforced.

**Ceiling:** Adding input sanitization and a deployment-level access control story would score 85+.

---

### Startup MVP Readiness: 24 / 100

**What works:** The value proposition is clear. The architecture can scale to the full PRD without breaking backward compatibility. The database schema and governance model are production-appropriate. Manual claim intake is real. NCCI PTP bundling is now a genuine rule engine check, not a demo prop — a claim with the 80053/80048 pair will be flagged correctly.

**What's missing:** Not deployable as a product. No LLM agents. No coverage validation. No evaluation metrics. A paying customer would see 3 findings on the worked example, with MUE and NPI gaps undetected. The system cannot deliver its core value proposition until Phases 3–7 are complete.

**Ceiling:** Completing Phases 3–5 would yield a deployable MVP scoring 55+. The current score is capped by the absent agent layer, which is the product's entire reason to exist.

---

## 8. Competitive Assessment

### vs. Typical PM Portfolio (no code)

**Advantage:** This project has running code, a 127-test suite, a proper database, and documented architecture decisions. Most PM portfolios have a PRD PDF and a Figma mockup. This is categorically stronger — it demonstrates you can ship, not just specify.

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

### Phase 3: Complete Deterministic Layer (NCCI done — MUE, NPI, ICD-10-CM remaining)

**Status:** In progress. NCCI PTP is complete (Sprint 5). Three items remain.

**Why finish Phase 3 before Phase 4:**

The Coverage Validation Agent (Phase 5) only adds value when the deterministic rule layer it complements is credible. A reviewer who sees a real NCCI bundling finding but no MUE check will ask "what about unit limits?" — and the answer today is "not implemented." More practically, Phase 3 is the last no-LLM, no-infrastructure sprint: MUE, NPI, and ICD-10-CM are deterministic file lookups, testable without network access or API keys. Completing Phase 3 takes the deterministic layer from ~35% done to ~95% done and resolves 3 of the 5 remaining HIGH debt items.

**Remaining Phase 3 work:**

| Task | Debt item | Time |
|---|---|---|
| MUE table lookup, MAI-aware severity (MAI=1→HIGH, MAI=2/3→MEDIUM) | TD-02 | 2–3 days |
| NPI Luhn check digit + NPPES live REST API client | TD-03 | 1–2 days |
| ICD-10-CM FY2026 reference file loader (replaces 2 hardcoded rules) | TD-06 | 2–3 days |
| Expand `test_rules.py` from stub to 20+ real tests | TD-08 (partial) | 1–2 days |

**Dependencies (all satisfied):**
- `rules/mue.py` docstring interface designed ✅
- `rules/npi.py` docstring interface designed ✅
- `rules/code_validity.py` swap points documented ✅
- `data/reference/` directory established ✅
- CMS MUE and ICD-10-CM files available for download (quarterly/annual)

**Estimated remaining effort:** 1–2 weeks

**Impact on completing Phase 3:**
- TD-02, TD-03, TD-06 resolved (3 of 5 remaining HIGH items)
- Claims with unit violations flagged with MAI-appropriate severity
- NPI failure short-circuits rule engine before NCCI/MUE (as designed)
- Code validity moves from 2 hardcoded rules to reference file
- Unblocks Phase 4 (RAG pipeline) and Phase 5 (Coverage Agent)
- PRD P0 requirements for MUE, NPI, and ICD-10-CM promoted from Not Started/Partial to Complete

---

## 10. Recommended Development Roadmap

Phases in priority order, reflecting the dependency chain and demo impact at each step.

### Phase 3: Complete Deterministic Layer (1–2 weeks remaining) — IN PROGRESS

NCCI PTP complete (Sprint 5). Remaining: MUE table with MAI-aware severity, NPI Luhn + NPPES live check, ICD-10-CM reference file loader. End state: every P0 deterministic rule is backed by real CMS reference data.

**Remaining deliverables:** MUE table (MAI=1→HIGH, MAI=2/3→MEDIUM); NPI Luhn check + NPPES live API client; ICD-10-CM FY2026 loader replacing 2 hardcoded code validity rules; `test_rules.py` expanded to 20+ tests; TD-02, TD-03, TD-06 resolved.

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

**Yes, with caveats.** The project demonstrates engineering judgment, healthcare domain expertise, and governance sophistication that most PM portfolios lack entirely. 11 ADRs, a Technical Debt Register with explicit deferral rationale, and a phased roadmap with shipped milestone commits are signals of professional rigor. The NCCI PTP rule engine now uses real CMS data (v322r0, ~1.73M pairs) — one of the project's three demo findings is now fully verifiable and citable, not synthetic.

However, the AI layer — the entire point of the project — does not exist yet. A knowledgeable reviewer who digs past the UI will find stubs in `agents/`. The honest framing today is: "I built the governance and rule layer; the LLM agents are the next phase." That is a defensible position if stated directly and proactively.

**Minimum threshold for unqualified portfolio use:** Complete Phase 5 (first working LLM agent with real LCD citations). That transforms the narrative from "I designed an AI system" to "I built one."

---

### Is this portfolio-ready today?

**Yes, for the right audience.** Best suited for demos where you want to demonstrate:
- Healthcare RCM domain knowledge (NCCI, MUE, NPI, LCD/NCD, E/M coding)
- AI governance design (citation-first, audit trail, human-in-loop)
- Engineering judgment under constraint (rules-before-LLM, deterministic over generative where possible)
- PM-level thinking (PRD → ADRs → tech debt register → phased roadmap)

Less suited for demos where the evaluator will probe AI implementation depth (prompt engineering, RAG quality, model evaluation). For those, wait until Phase 5 ships.

**Best use today:** PM portfolio discussions, product design discussions, healthcare AI governance conversations.

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
