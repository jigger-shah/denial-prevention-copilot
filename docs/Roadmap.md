# Development Roadmap
## Denial Prevention Copilot

**PRD vision:** An explainable, agentic pre-submission copilot that prevents denials before they happen — AI researches, humans decide.

**Roadmap philosophy:** Each phase builds on the previous one without breaking it. Governance infrastructure is built before the AI it governs. Deterministic correctness is established before generative reasoning is added. Every phase ships working, testable software.

---

## Phase 0 — Environment Setup ✅ Complete

**Commit:** `11f62cf`

### Objectives
Establish the project skeleton, dependencies, and conventions that all future phases build on.

### Deliverables
- Full directory structure: `rules/`, `agents/`, `retrieval/`, `db/`, `app/`, `data/`, `tests/`, `docs/`
- `requirements.txt` with all anticipated dependencies
- `CLAUDE.md` with architecture description, commands, and design constraints
- `README.md` with project overview
- Module docstrings for all planned files (stub skeleton)
- `.gitignore` with Python, macOS, and project-specific patterns

### Dependencies
None — this is the foundation.

### Success Criteria
- `streamlit run app/main.py` runs without error (blank but functional)
- `pytest tests/` runs without error (0 tests collected is acceptable)
- Directory structure matches the architecture described in CLAUDE.md
- Repository is pushed to GitHub

---

## Phase 1 — Deterministic Claim Review v0.1 ✅ Complete

**Commit:** `cf322d9`  
**Tests:** 12 tests, all passing

### Objectives
Implement the rule layer with the two most common denial triggers, build the Streamlit UI, and establish the test pattern for all future rule modules.

### Deliverables
- `rules/models.py`: `ClaimIn` dataclass (input contract for all rules)
- `rules/ncci.py`: NCCI PTP check (1 hardcoded edit pair — 80048/80053)
- `rules/code_validity.py`: dx-procedure conflict (Z00.00 vs. problem E/M) and missing modifier 25
- `rules/rule_engine.py`: `load_claim()`, `review_claim()`, `overall_risk()`
- `app/main.py`: Streamlit UI with claim selector, color-coded findings, Accept/Override controls
- `data/synthetic/sample_claims.json`: 5 synthetic claims covering the PRD worked example and 4 edge cases
- `tests/test_rule_engine.py`: 12 tests (NCCI, dx conflict, modifier, risk scoring, clean claim, ordering)

### Dependencies
- Phase 0 complete

### Success Criteria
- CLM-001 (PRD worked example) produces 3 findings: HIGH NCCI bundling, HIGH dx conflict, MEDIUM missing modifier 25
- CLM-002 (clean URI claim) produces zero HIGH findings and `overall_risk() == "CLEAN"`
- Accept and Override controls work; Override requires a reason
- All 12 tests pass without network access or external dependencies

---

## Phase 1.5 — Pre-Audit Model Refactor ✅ Complete

**Commit:** `dc681f2`  
**Tests:** 20 tests, all passing (+8)

### Objectives
Prepare the data model for audit persistence. This phase has no visible UI changes — all changes are in the data contract between the rule layer, UI, and future DB.

### Deliverables
- `Citation` dataclass added to `rules/models.py` with `source`, `doc_id`, `section`, `edition`, `effective_date`, `excerpt`
- `Finding.citation` promoted from `str` to `Citation`
- `Finding.finding_id` added (SHA-256, stamped by rule engine)
- `Finding.source` added (`"rule_layer"` default)
- `rules/ncci.py` and `rules/code_validity.py` updated to construct `Citation` objects
- `app/main.py`: session state re-keyed from positional to `finding_id`-based; `_citation_caption()` helper; "View source excerpt" expander
- 8 new structure tests covering finding_id stability, Citation shape, citation content

### Dependencies
- Phase 1 complete

### Success Criteria
- All 20 tests pass
- `Finding.citation` is a `Citation` object (not a string) on every finding
- `finding_id` is a 12-char hex string, stable across two runs of the same claim
- `source == "rule_layer"` on all current findings

---

## Phase 2 — Governance & Audit Logging ✅ Complete

**Commit:** `ee45738`  
**Tests:** 35 tests, all passing (+15)

### Objectives
Implement the complete human decision workflow and append-only audit persistence. Governance before AI.

### Deliverables
- `db/audit_repository.py`: `AuditDecision` dataclass + `AuditRepository` with `initialize_database()`, `save_decision()`, `get_decisions()`, `export_decisions_csv()`
- `db/schema.py`: column reference documentation for `audit_decisions` table
- `db/audit.db`: SQLite database (gitignored), created on first run
- `app/main.py` updated:
  - Sidebar reviewer name input (required to save)
  - Two-tab layout: "🔍 Review Claim" and "📋 Audit Trail"
  - Save Decision button per finding (visible after accept/override)
  - "Manual Review Recommended" badge for confidence < 70%
  - Audit Trail tab with claim_id/reviewer filters and CSV export
- Governance validation in `save_decision()`: finding_id required, citation required, override reason required
- Bug fix: split widget key from persistent storage key for override reason
- `tests/test_audit.py`: 15 tests covering persistence, validation, filtering, CSV export

### Dependencies
- Phase 1.5 complete (Citation dataclass, finding_id must exist before they can be persisted)

### Success Criteria
- Accepted decision saves to `audit_decisions` table and appears in Audit Trail tab
- Override with reason saves successfully; override without reason raises `ValueError`
- Finding without citation_source raises `ValueError` in `save_decision()`
- CSV export contains all 18 expected columns
- All 35 tests pass

---

## Phase 2.5 — Policy Intelligence Foundation ✅ Complete

**Tests:** 55 tests, all passing (+20)

### Objectives
Replace hollow synthetic citation strings with structured, evidence-backed policy references using a curated local dataset. Make the app feel evidence-backed before the real CMS pipeline is built.

### Deliverables
- `data/reference/policy_examples.json`: 5 curated public-policy-style references (NCCI PTP 80048/80053, ICD-10 Z00.00 preventive context, Modifier 25 guidance, LCD venipuncture illustrative, MUE panel units illustrative)
- `retrieval/policy_repository.py`: JSON-backed policy reference service (`load_policy_references`, `find_policy_by_document_id`, `find_policies_by_codes`, `get_citation_detail`)
- `rules/ncci.py` updated: doc_id `NCCI_PTP_80048_80053_SAMPLE`, effective_date `2000-01-01`, substantive excerpt
- `rules/code_validity.py` updated: doc_ids `ICD10_Z00_PREVENTIVE_CONTEXT_SAMPLE` and `NCCI_MODIFIER_25_SAMPLE`, FY2026 edition, effective dates, substantive excerpts
- `app/main.py` updated: `_render_citation_detail()` helper; "📄 View policy detail" expander with source, doc_id, section, edition, effective_date, title, source URL, excerpt, notes
- `db/audit_repository.py` updated: `citation_effective_date` column added to schema + backward-compatible `ALTER TABLE` migration in `initialize_database()`
- `tests/test_policy_repository.py`: 20 tests covering JSON loading, document_id lookup, code-based lookup, citation resolution, audit migration

### Dependencies
- Phase 2 complete (Citation dataclass, AuditRepository must exist)

### Success Criteria
- All 3 rule findings (NCCI PTP, dx-procedure conflict, missing modifier 25) have `citation.doc_id` values that resolve in `policy_examples.json`
- "📄 View policy detail" expander shows title, source URL, and structured policy excerpt for each finding
- `citation_effective_date` is persisted in the audit log
- Backward-compatible migration: existing Sprint 2 `audit.db` databases get the new column added safely
- All 55 tests pass
- No LLM calls, no Chroma, no live CMS API

### Future replacement point
`retrieval/policy_repository.py:_load_policy_references()` is the seam. Replace with a ChromaDB query after `retrieval/ingest.py` and `retrieval/vector_store.py` are implemented. The JSON file can then be removed. The public interface (`find_policy_by_document_id`, `find_policies_by_codes`, `get_citation_detail`) and all callers stay unchanged.

---

## Phase 2.75 — Manual Claim Intake with Service-Line Grid ✅ Complete

**Tests:** 83 tests, all passing (+28)

### Objectives
Enable users to submit arbitrary claims directly from the UI rather than selecting from a fixed JSON file. Makes the demo interactive and unlocks user-guided testing of the rule engine with real coding scenarios.

### Deliverables
- `app/claim_intake.py`: `build_manual_claim()`, `get_payer_id()`, `validate_npi()`, `normalize_code()`; payer name → payer ID mapping; `WORKED_EXAMPLE` constant; no Streamlit imports — fully unit-testable
- `app/__init__.py`: empty package marker for consistent `from app.claim_intake import ...`
- `app/main.py` updated:
  - Mode selector radio (Sample Claim | Manual Claim Entry) in Review Claim tab
  - Manual mode: claim header (Claim ID, Payer dropdown with auto-populated Payer ID, Provider NPI, Specialty, Notes)
  - PHI warning: "Do not enter PHI. Synthetic or de-identified notes only."
  - Service-line coding grid: CPT/HCPCS, Modifier 1, Modifier 2, ICD-10 x4 per row; dynamic row add/remove
  - Add Service Line, Clear Form, Load Worked Example, Review Claim buttons
  - Service-line data → `build_manual_claim()` → `load_claim()` → rule engine (no change to downstream pipeline)
  - Sample Claim mode extracted to `_render_sample_mode()`; Manual mode to `_render_manual_mode()`
- `rules/rule_engine.py` updated: `load_claim()` now accepts both `"payer"` (sample claims) and `"payer_name"` (manual claims); `npi` and `place_of_service` default to `""` when absent
- `tests/test_claim_intake.py`: 28 tests covering `get_payer_id`, `validate_npi`, `normalize_code`, `build_manual_claim` (normalization, deduplication, blank-line exclusion, backward compat), and end-to-end integration (manual claim through rule engine)

### Constraints
- No PHI, no patient identifiers anywhere
- No external APIs, no LLM, no Chroma
- All existing sample-claim functionality preserved and regression-tested

### Success Criteria
- Load Worked Example (99214 + 80053 + 80048, Z00.00, Medicare) produces 3 findings: HIGH NCCI, HIGH dx conflict, MEDIUM missing modifier 25
- A blank CPT row does not add an empty string to `cpt_codes`
- The same manual claim produces the same `finding_id` values on repeated reviews (stability test)
- All 83 tests pass with no live API calls

---

## Phase 2.8 — File-Backed NCCI PTP Lookup ✅ Complete

**Tests:** 127 tests, all passing (+44)

### Objectives
Replace the single hardcoded NCCI PTP edit pair with a file-backed lookup using CMS quarterly xlsx files. Preserve synthetic fallback for portable environments.

### Deliverables
- `rules/ncci_loader.py`: `discover_ncci_files`, `inspect_ncci_files`, `load_ncci_ptp_edits`, `lookup_ncci_pair`; `functools.lru_cache` for O(1) lookup after first load
- `rules/ncci.py`: updated to use `ncci_loader`; synthetic fallback retained; `_file_backed_finding` and `_synthetic_finding` helpers; `combinations()` loop for all claim code pairs
- `data/reference/policy_examples.json`: added `CMS_NCCI_PTP_v322r0` entry with version, effective_date, source URL, and update instructions
- `requirements.txt`: added `openpyxl`
- `tests/test_ncci_loader.py`: 44 tests covering discovery, loader, lookup, file-backed rule behavior, synthetic fallback, and real-file integration
- Documentation updated: ADR-011, TD-01 resolved, Roadmap, Demo Script

### Data
- Files: `ccipra-v322r0-f1.xlsx` through `ccipra-v322r0-f4.xlsx` (CMS NCCI Practitioner PTP, v322r0, effective 2026-07-01)
- Active pairs: ~1.73M (filtered to deletion_date == "*")
- 80053/80048 pair: found in f4, modifier 0 (no bypass), effective 2000-07-01

### Performance
- First load: ~54 seconds (xlsx reading, one-time per Python process)
- Subsequent lookups: O(1) via Python dict
- Cached via `functools.lru_cache` — not reloaded during Streamlit session

### Constraints
- No MUE ingestion in this sprint (deferred to Phase 3)
- No LLM calls, no live APIs, no ChromaDB
- Synthetic fallback retained for portability

### Success Criteria
- All 127 tests pass
- Worked example (80053 + 80048 + 99214 + Z00.00) still produces 3 findings (HIGH NCCI, HIGH dx conflict, MEDIUM missing modifier 25)
- NCCI finding citation shows `doc_id = "CMS_NCCI_PTP_v322r0"`, `edition = "v322r0"`, `effective_date = "2026-07-01"`
- Citation excerpt includes source xlsx filename and NCCI version

---

## Phase 3 — Complete the Deterministic Layer

**Status:** In Progress — Phase A complete (NCCI PTP + Units + MUE done; NPI and ICD-10-CM remaining)
**Estimated scope:** 1–2 additional implementation sessions

### Objectives
Replace all hardcoded rule data with real CMS reference files. Add NPI live validation. This phase makes the rule layer production-complete before any LLM is introduced.

### Deliverables

**Rule layer — real data:**
- `rules/ncci.py`: ✅ File-backed xlsx loader; ~1.73M active pairs (v322r0); `doc_id` and `edition` from CMS file
- `rules/mue_loader.py`: ✅ **NEW (Phase A).** File-backed MUE table loader; column-name discovery; lru_cache; synthetic fallback
- `rules/mue.py`: ✅ **Implemented (Phase A).** `check_mue_limits()` with MAI-aware severity; wired into rule engine
- `app/claim_intake.py`: ✅ **Updated (Phase A).** `build_manual_claim()` populates `ClaimIn.units`; units column in service-line grid
- `rules/npi.py`: 🔜 Luhn check digit validation; NPPES live REST API client; HIGH finding for deactivated/invalid NPI; graceful timeout handling
- `rules/code_validity.py`: 🔜 ICD-10-CM FY reference file loader (replaces Z00.00 hardcode); HCPCS Level II validity; expanded modifier rules
- `rules/rule_engine.py`: 🔜 wire NPI into `review_claim()`; NPI failure short-circuits before NCCI/MUE (MUE already wired ✅)

**Reference data:**
- `data/reference/ncci_ptp_<quarter>.csv` (downloaded, gitignored)
- `data/reference/ncci_mue_<quarter>.csv` (downloaded, gitignored)
- `data/reference/icd10cm_fy<year>.csv` (downloaded, gitignored)
- `data/reference/hcpcs_<quarter>.csv` (downloaded, gitignored)
- `data/reference/README.md` updated with download instructions

**Tests:**
- `tests/test_rules.py`: ✅ 35 tests implemented (Phase A): MUE (MAI=1/2/3, limits, fallback, file-backed xlsx/csv, multi-code, integration), NCCI regression, code_validity regression. 🔜 NPI tests pending Phase B.

**Cleanup:**
- `db/audit.py` stub removed or replaced with a comment pointing to `audit_repository.py`
- `ClaimIn` field types tightened to `list[str]` and `dict[str, int]`

### Dependencies
- Phase 2.75 complete
- CMS quarterly NCCI and MUE files downloaded
- CMS ICD-10-CM FY2026 reference file downloaded

### Success Criteria
- CLM-001 reviewed with real NCCI data produces the same 3 findings as today (regression test)
- A claim with a code billing more units than its MUE limit produces a HIGH or MEDIUM finding
- A claim with an invalid or deactivated NPI produces a HIGH finding and the review short-circuits
- A manually-entered claim with an invalid NPI is rejected at the NPI rule before NCCI/MUE run
- 83+ total tests, all passing

---

## Phase 4 — LCD/NCD Retrieval Pipeline

**Status:** Future  
**Estimated scope:** 2–3 implementation sessions

### Objectives
Build the data pipeline that fetches CMS coverage policies (LCDs and NCDs) and indexes them for semantic retrieval. This phase produces no visible UI changes — it creates the data foundation that Phase 5 depends on.

### Deliverables
- `retrieval/ingest.py`: CMS Coverage API client; fetches LCDs, NCDs, and coverage articles; saves to `data/reference/coverage/` with metadata (document_id, title, effective_date, contractor)
- `retrieval/chunking.py`: section-aware splitting that keeps policy sections (Indications, Limitations, Covered Diagnoses, Documentation Requirements) intact; each chunk carries `document_id`, `section_heading`, `effective_date`, `chunk_index`
- `retrieval/vector_store.py`: ChromaDB wrapper with `index(chunks)` and `query(text, n_results, filters)`; default to built-in embedding function; idempotent re-indexing via `document_id + chunk_index` as ChromaDB document ID
- Ingestion script: `scripts/ingest_coverage.py` or a Streamlit admin panel button
- `data/reference/coverage/` populated with at least one LCD covering a common Medicare scenario (e.g., LCD for metabolic panel, L35025 or equivalent)
- `retrieval/chroma_db/` directory created and gitignored

### Dependencies
- Phase 3 complete (code validity and NPI checks ensure the claim reaching the agent layer is deterministically clean first)
- CMS Coverage API access (free, no authentication required)

### Success Criteria
- `vector_store.query("Z00.00 encounter for general adult medical examination", n_results=5)` returns at least one LCD chunk with a verifiable `effective_date`
- Each returned chunk carries `document_id`, `section_heading`, `effective_date` sufficient to construct a `Citation`
- Idempotent re-indexing: running ingestion twice does not create duplicate chunks

---

## Phase 5 — Coverage Validation Agent

**Status:** Future  
**Estimated scope:** 3–4 implementation sessions

### Objectives
Implement the first LLM agent. Wire Claude Sonnet 4.6 via the Anthropic SDK with structured tool use to reason over retrieved LCD/NCD text and produce cited medical necessity findings.

### Deliverables
- `agents/coverage_validation.py`: full implementation
  - Constructs retrieval query from claim's `icd10_codes` + `cpt_codes`
  - Queries `vector_store` for relevant LCD/NCD chunks
  - Calls Claude Sonnet 4.6 with structured tool use — forces the model to emit a `Finding`-shaped object with a citation that must reference a retrieved chunk
  - Suppresses findings if no relevant chunk was retrieved (no citation → no finding)
  - Returns `list[Finding]` with `source="coverage_validation"`
- `ANTHROPIC_API_KEY` guard in `app/main.py`
- `app/main.py` updated: "Run full review (with AI)" button that calls the coverage agent after the rule layer
- Progress indicator while agent runs
- `.env.example` added to repository

### Dependencies
- Phase 4 complete (ChromaDB index must exist for retrieval to work)
- `ANTHROPIC_API_KEY` set in `.env`

### Success Criteria
- CLM-001 (Z00.00 + 99214) produces a coverage finding with a `Citation.doc_id` referencing a real LCD document and `Citation.excerpt` containing verbatim policy text
- A claim with a diagnosis not covered by any LCD in the index produces no coverage finding (suppression working)
- The coverage finding can be saved to the audit log with a verifiable citation
- Finding precision on the existing 5 synthetic claims is ≥ 90% (manually verified)

---

## Phase 6 — Documentation Review Agent

**Status:** Future  
**Estimated scope:** 2–3 implementation sessions

### Objectives
Implement the documentation review agent that analyzes clinical note text for E/M level support, diagnosis specificity, and documentation completeness.

### Deliverables
- `agents/documentation_review.py`: full implementation
  - Accepts `claim.note_text` (synthetic only)
  - If no note attached: returns single LOW finding noting risk assessment is code-only
  - If note attached: LLM analysis for E/M MDM level support, ICD-10 specificity, required elements
  - Returns `list[Finding]` with `source="documentation_review"` and LOW default severity
- Sample clinical notes added to `data/synthetic/sample_claims.json` for at least 2 claims
- `app/main.py`: note text display in claim details expander (if present)

### Dependencies
- Phase 5 complete (orchestrator pattern established)
- Claude Sonnet 4.6 access

### Success Criteria
- A claim with a note attached receives at least one documentation finding with a specific recommendation
- A claim with no note attached receives a single LOW finding noting the limitation
- Documentation findings save to the audit log with the same governance controls as rule findings

---

## Phase 7 — Orchestrator + Denial Prevention Agent

**Status:** Future  
**Estimated scope:** 2–3 implementation sessions

### Objectives
Wire all agents into the orchestrator and implement the synthesis layer that produces the final `RiskAssessment`. This phase completes the four-agent architecture from PRD §9.

### Deliverables
- `agents/orchestrator.py`: full implementation
  - Validates claim schema
  - Runs rule layer synchronously; hard NPI failure short-circuits
  - Dispatches coverage and documentation agents in parallel (ThreadPoolExecutor)
  - Collects all findings and passes to Denial Prevention Agent
  - If aggregate confidence < threshold: sets `escalation_required=True`
- `agents/denial_prevention.py`: full implementation
  - Aggregates findings from all sources
  - Computes `RiskAssessment(score, findings, escalation_required, checks_run)`
  - Applies denial pattern heuristics (payer-specific CARC patterns, severity adjustments)
  - No LLM call — deterministic synthesis
- `db/` extended: `claims` and `findings` tables added to `AuditRepository` (or a new `ClaimRepository`)
- `app/main.py`: escalation banner when `escalation_required=True`
- `tests/test_orchestrator.py`: full implementation with mocked LLM responses

### Dependencies
- Phases 5 and 6 complete

### Success Criteria
- Full review of CLM-001 produces all 4 finding types: NCCI (rule), dx conflict (rule), coverage (agent), documentation (agent)
- Parallel agent dispatch completes in < 30 seconds (PRD §7 Story 1 acceptance criteria)
- Claims with aggregate confidence < 70% display an escalation banner
- `RiskAssessment` is persisted to the audit log
- `tests/test_orchestrator.py` passes with mocked LLM responses

---

## Phase 8 — Evaluation Framework

**Status:** Future  
**Estimated scope:** 1–2 implementation sessions

### Objectives
Build the golden-set evaluation infrastructure so that agent quality can be measured, regression-tested, and discussed with precision in interviews.

### Deliverables
- `data/synthetic/golden_claims.json`: 20–30 synthetic claims with seeded denial risks and expected findings (ground truth)
- `pytest.ini` or `pyproject.toml` updated with `golden` marker definition
- `tests/test_golden.py`: implements `pytest -m golden` evaluation
  - Loads golden claims
  - Runs full orchestrator review
  - Asserts precision ≥ 90% and recall ≥ 85% against expected findings
  - Tracks citation coverage (target: 100%)
- `scripts/evaluate.py`: standalone script that prints a precision/recall table per agent and per finding type

### Dependencies
- Phase 7 complete (all agents wired)

### Success Criteria
- `pytest tests/ -m golden` runs without error and prints a precision/recall report
- Precision ≥ 90% on golden set
- Recall ≥ 85% on golden set
- Citation coverage = 100% (every finding in the golden set has a citation)

---

## Phase 9 — Portfolio Publication

**Status:** Future  
**Estimated scope:** 1 session

### Objectives
Polish the repository for public visibility and portfolio use.

### Deliverables
- `README.md` rewritten with: project overview, architecture diagram, setup instructions, screenshots, and the PRD summary
- 3–5 screenshots of the running app (claim review, findings, audit trail) committed to `docs/screenshots/`
- `CONTRIBUTING.md` or note in README explaining the synthetic-data-only constraint
- GitHub repository set to public
- GitHub Actions CI (optional): `pytest tests/` on push to main

### Dependencies
- Phase 2+ complete (enough to screenshot)
- No PHI in any committed file (verified)

### Success Criteria
- A recruiter or interviewer can clone the repository, follow the README, and run the app with `streamlit run app/main.py` in under 5 minutes
- Screenshots clearly show the findings panel, citation display, audit trail, and export

---

## Phase 10 — Streamlit Cloud Deployment

**Status:** Future  
**Estimated scope:** 1 session

### Objectives
Deploy the application to Streamlit Cloud so it is accessible via a public URL without local setup.

### Deliverables
- `requirements.txt` verified against Streamlit Cloud's Python environment
- Streamlit Cloud secrets configured for `ANTHROPIC_API_KEY`
- `st.secrets` used instead of `os.getenv` for cloud deployment
- `db/audit.db` path updated to use a temp directory (cloud deployments don't have persistent disk)
- Live URL linked from GitHub README

### Dependencies
- Phase 9 complete (repository is public and polished)
- Streamlit Cloud account

### Success Criteria
- The application loads at the Streamlit Cloud URL with no errors
- Synthetic claims can be reviewed; findings display correctly
- If agents are wired: a full review completes within 30 seconds
- Audit trail tab works (using session-scoped in-memory SQLite for cloud)

---

## Milestone Summary

| Phase | Status | Key Output | PRD Priority |
|---|---|---|---|
| 0 — Environment Setup | ✅ | Skeleton, CLAUDE.md | Setup |
| 1 — Deterministic Review | ✅ | Rule layer, UI, 12 tests | P0 |
| 1.5 — Pre-Audit Refactor | ✅ | Citation, finding_id, source | P0 (prep) |
| 2 — Governance & Audit | ✅ | AuditRepository, audit trail, 35 tests | P0 |
| 2.5 — Policy Intelligence | ✅ | Structured citations, policy detail view, 55 tests | P0 (prep) |
| 2.75 — Manual Claim Intake | ✅ | Service-line grid, build_manual_claim, 83 tests | P0 |
| 2.8 — File-Backed NCCI PTP | ✅ | ncci_loader, ~1.73M active pairs, 127 tests | P0 |
| 3 — Complete Deterministic Layer | 🔄 In Progress | Phase A done (Units + MUE); NPI and ICD-10-CM remaining | P0 |
| 4 — LCD/NCD Retrieval | 🔜 | ChromaDB, CMS ingestion | P0 (dep) |
| 5 — Coverage Agent | 🔜 | First LLM agent, RAG findings | P0 |
| 6 — Documentation Agent | 🔜 | Clinical note analysis | P1 |
| 7 — Orchestrator + Synthesis | 🔜 | Full 4-agent pipeline | P0 |
| 8 — Evaluation | 🔜 | Golden set, precision/recall | P0 metric |
| 9 — Portfolio Publication | 🔜 | Public README, screenshots | Portfolio |
| 10 — Streamlit Cloud | 🔜 | Live public URL | Portfolio |
