# Development Roadmap
## Denial Prevention Copilot

**PRD vision:** An explainable, agentic pre-submission copilot that prevents denials before they happen — AI researches. Humans decide.

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

**Status:** Phase A + Phase B + Sprint 8 (UI/UX) complete — deterministic layer is MVP-complete. ICD-10-CM loader deferred here, later delivered in Phase 8.5 (v1.5).
**Estimated scope:** ICD-10-CM loader deferred (see Phase 8.5); all other deterministic checks implemented and tested

### Objectives
Replace all hardcoded rule data with real CMS reference files. Add NPI live validation. This phase makes the rule layer production-complete before any LLM is introduced.

### Deliverables

**Rule layer — real data:**
- `rules/ncci.py`: ✅ File-backed xlsx loader; ~1.73M active pairs (v322r0); `doc_id` and `edition` from CMS file
- `rules/mue_loader.py`: ✅ **NEW (Phase A).** File-backed MUE table loader; column-name discovery; lru_cache; synthetic fallback
- `rules/mue.py`: ✅ **Implemented (Phase A).** `check_mue_limits()` with MAI-aware severity; wired into rule engine
- `app/claim_intake.py`: ✅ **Updated (Phase A).** `build_manual_claim()` populates `ClaimIn.units`; units column in service-line grid
- `rules/npi.py`: ✅ **Implemented (Phase B).** `luhn_valid()` (Luhn with "80840" prefix); `lookup_nppes()` (NPPES API v2.1, 2s timeout); `check_npi()` with HIGH/MEDIUM/no-finding paths; SHORT-CIRCUITS rule engine on HIGH; NPPES errors silenced
- `rules/code_validity.py`: Z00.00 dx-procedure conflict and modifier-25 rules unchanged. ✅ ICD-10-CM FY reference file loader delivered separately in `rules/icd10_loader.py`/`rules/icd10.py` (Phase 8.5 / v1.5) rather than inside this module. HCPCS Level II validity and expanded modifier rules remain 🔜.
- `rules/rule_engine.py`: ✅ **Updated (Phase B + Sprint 8).** NPI runs first; HIGH finding short-circuits before NCCI/MUE/code_validity; MEDIUM NPI finding included but does not short-circuit. `CHECKS_RUN` exported for UI consumption.
- `app/main.py`: ✅ **Updated (Sprint 8).** Checks-run always visible after review (not just on CLEAN); NPI short-circuit message displayed; "Not provided" for blank NPI in sample mode; blue primary button via `.streamlit/config.toml`.

**Reference data:**
- `data/reference/ncci_ptp_<quarter>.csv` (downloaded, gitignored)
- `data/reference/ncci_mue_<quarter>.csv` (downloaded, gitignored)
- `data/reference/icd10cm_fy<year>.csv` (downloaded, gitignored)
- `data/reference/hcpcs_<quarter>.csv` (downloaded, gitignored)
- `data/reference/README.md` updated with download instructions

**Tests:**
- `tests/test_rules.py`: ✅ 48 tests implemented (Phase A + B): MUE (MAI=1/2/3, limits, fallback, file-backed xlsx/csv, multi-code, integration), NCCI regression, code_validity regression, NPI (luhn_valid, format, Luhn, NPPES mock, short-circuit, no-finding paths).
- `tests/test_rule_engine.py`: ✅ 3 new tests added (Sprint 8): CHECKS_RUN structure, CHECKS_RUN rule coverage, NPI short-circuit engine behavior. (23 tests total)

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

**Status:** ✅ Complete (Sessions 1A–1D), split into sub-sessions to avoid stacking multiple unverified layers at once. The ChromaDB index itself is not pre-seeded with a real corpus — see Session 1D note below.
**Estimated scope:** 4 implementation sessions (1A–1D)

### Objectives
Build the data pipeline that fetches CMS coverage policies (LCDs and NCDs) and indexes them for semantic retrieval. This phase produces no visible UI changes until 1D — it creates the data foundation that Phase 5 depends on.

### Session 1A — Chunking ✅ Complete
- `retrieval/chunking.py`: `chunk_document()` — section-aware splitting that keeps policy sections (Indications, Limitations, Covered Diagnoses, Documentation Requirements) intact; each chunk carries `document_id`, `document_title`, `section_heading`, `effective_date`, `chunk_index`
- Long sections split on paragraph boundaries via `_split_section_text()`; hard character split as a fallback for a single paragraph exceeding `max_chunk_chars`
- `tests/test_chunking.py`: 11 tests (single section, multi-section sequential indexing, long-section splitting, blank-section skip, missing-key validation, hard-split fallback)
- No CMS API, no ChromaDB, no changes to `coverage_validation.py` or any agent — chunking only

### Session 1B — Vector Store ✅ Complete
- `retrieval/vector_store.py`: `VectorStore` class wrapping a persistent ChromaDB collection; `index(chunks)` (idempotent upsert keyed on `document_id::chunk_index`), `query(text, n_results, filters)` (returns plain dicts, never ChromaDB's native `QueryResult`), `count()`
- Constructed per `persist_directory` (no module-level singleton) so production and tests get fully isolated instances
- `tests/test_vector_store.py`: 12 tests using `tmp_path` for an isolated ChromaDB instance per test — idempotent re-indexing, empty-index query returns `[]`, metadata fields needed for `Citation` construction are preserved, `where`-filter querying, cross-instance isolation
- `chromadb` installed in `.venv` (was listed in `requirements.txt` but not previously installed); default embedding model (`all-MiniLM-L6-v2`) downloads once to `~/.cache/chroma` on first use
- No CMS API, no real coverage data seeded, no changes to `coverage_validation.py` or `ingest.py`

### Session 1C — CMS Ingestion ✅ Complete
- `retrieval/ingest.py`: CMS Coverage API client (`fetch_lcd`, `fetch_ncd`, `fetch_article`) against `https://api.coverage.cms.gov`; normalizes responses into the `chunking.py` document contract; saves raw JSON to `data/reference/coverage/{type}_{id}.json`; local-cache-first with `force_refresh` override; retry/backoff (up to 3 attempts) on HTTP 429/5xx and connection errors; raises `CoverageAPIError` on non-retryable failures or retry exhaustion
- `scripts/ingest_coverage.py`: CLI (`--type`, `--id`, `--output-dir`, `--force-refresh`, `--dry-run`)
- `tests/test_ingest.py`: 15 tests with mocked `requests.get` (no live API calls) — success paths for LCD/NCD/Article, cache-hit skips network, force-refresh bypasses cache, 404 and connection-error handling, 429 retry-then-succeed and retry-exhaustion, missing-field defaults, raw JSON shape, CLI dry-run/success/error paths
- `data/reference/coverage/` added to `.gitignore` — raw CMS downloads are not committed, same pattern as `data/reference/ncci/`
- **Field-name caveat:** the CMS Coverage API's exact response schema could not be verified against a live call from this environment (outbound network restricted). `normalize_lcd/_ncd/_article()` check multiple plausible field names per CMS documentation conventions and default missing fields gracefully; this needs verification against one real API response before being relied on for an actual demo (see TD-18)

### Session 1D — Coverage Agent v2 Swap ✅ Complete
- `agents/coverage_validation.py`: `_retrieve_policies()` queries `vector_store` first (`_retrieve_from_vector_store()`); falls back to JSON `policy_repository.find_policies_by_codes()` (`_retrieve_from_json_fallback()`) when the vector store is empty, returns nothing for the query, or raises any exception
- Vector chunk results are converted to the existing policy-dict shape via `_vector_result_to_policy()` before reaching `_build_user_message()`/`_parse_response()` — neither of those, nor the tool schema, citation grounding, or audit workflow, changed
- `_MAX_POLICIES` cap (3) and the "no retrieved policy → no AI finding" rule preserved across both retrieval paths
- Before coding: made live calls against `api.coverage.cms.gov` to resolve TD-18 (see Technical_Debt_Register.md) — found and fixed a real bug in `retrieval/ingest.py` (responses are wrapped in a `{"meta", "data": [...]}` envelope, not flat dicts), corrected endpoint URLs, added the missing Bearer-token flow for LCD/Article, and corrected every guessed field name against live LCD/NCD/Article records
- 24 tests in `tests/test_coverage_validation.py` (up from 14) using a `MagicMock` for `_get_vector_store()` — no real ChromaDB or Anthropic calls
- **ChromaDB index is not pre-seeded.** A fresh checkout's vector store is empty, so every claim review uses the JSON fallback until someone runs `scripts/ingest_coverage.py` + chunking + indexing for a real set of documents (intentionally out of scope for this phase — no bulk download, no large seeded corpus)

### Session 1D Follow-Up — Excerpt Quality Fix + Live Validation ✅ Complete
- Seeded a minimal real corpus (2 documents: LCD 33431 "HbA1c", NCD 98 "Blood Glucose Testing") to validate the vector path end-to-end with a real Anthropic call. **Local-only** — `data/reference/coverage/` and `retrieval/chroma_db/` are gitignored, so a fresh clone always starts with an empty index and JSON-fallback behavior, regardless of what's seeded on any one machine.
- Found and fixed a real bug: `retrieval/chunking.py`'s long-paragraph fallback cut text at a fixed character offset, not a sentence boundary, producing citation excerpts like `"). This NCD lists the ICD-10 codes..."`. Replaced with sentence-boundary-aware splitting (`_split_long_paragraph()`) plus defensive entity/tag cleanup and leading-fragment trimming (`starts_with_dangling_fragment()`, `trim_leading_fragment()`, now public). `agents/coverage_validation.py` gained `_clean_citation_excerpt()` as a second line of defense against the model itself echoing a fragment. 12 new tests; total 289 passing. Committed as `b92e8d7`.
- **Operational note:** ChromaDB's embedded HNSW index does not refresh in a long-lived process after a *separate* process re-indexes the same `retrieval/chroma_db/` directory — `query()` raises `"Error creating hnsw segment reader: Nothing found on disk"`, silently caught and routed to the JSON fallback. **Restart the Streamlit process after running ingestion/indexing** to pick up newly seeded documents. Tracked as TD-21 (self-healing retry is a possible future fix, not implemented).
- See `docs/Architecture_Decisions.md` ADR-014 and `docs/Technical_Debt_Register.md` TD-20/TD-21 for full detail.

### Dependencies
- Phase 3 complete (code validity and NPI checks ensure the claim reaching the agent layer is deterministically clean first)
- CMS Coverage API access (free, no authentication required) — needed starting Session 1C

### Success Criteria
- `vector_store.query("Z00.00 encounter for general adult medical examination", n_results=5)` returns at least one LCD chunk with a verifiable `effective_date`
- Each returned chunk carries `document_id`, `section_heading`, `effective_date` sufficient to construct a `Citation`
- Idempotent re-indexing: running ingestion twice does not create duplicate chunks

---

## Phase 5 — Coverage Validation Agent

**Status:** v1+ complete (JSON-backed retrieval, no ChromaDB); 18 LCD/NCD entries, 6 validated demo scenarios (Sprint 10 Option A); ChromaDB RAG upgrade deferred to Phase 5 v2  
**Estimated scope (v2 ChromaDB upgrade):** 2–3 implementation sessions

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

**Status:** Deferred / Under Evaluation. Remains part of the product vision (PRD §9's four-agent architecture) but is not required for the current MVP or public release. Revisit before public release.
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
- Phase 7 (light orchestrator) and Phase 7.5 (Coding Validation Agent) complete — done, see below. Full parallel dispatch is not a prerequisite; Phase 6 can be wired into `agents/orchestrator.py` as an additional sequential or parallel call whenever it is implemented.
- Claude Sonnet 4.6 access

### Success Criteria
- A claim with a note attached receives at least one documentation finding with a specific recommendation
- A claim with no note attached receives a single LOW finding noting the limitation
- Documentation findings save to the audit log with the same governance controls as rule findings

### Deferral rationale (decided alongside Phase 7 scoping)
The MVP already demonstrates strong AI product value through deterministic CMS validation, real CMS RAG retrieval, the Coverage Validation Agent, citation grounding, human review, and the audit trail. A second LLM agent adds breadth, not the missing piece — Unified Review (Phase 7) and risk synthesis were judged the higher-priority next milestone. Documentation Review is not removed from the roadmap; it is sequenced after Golden Set Evaluation / public-release work, to be revisited explicitly before public release.

---

## Phase 7 — Light Orchestrator + Denial Prevention Agent (Unified Review) ✅ Complete

**Tests:** 308 tests, all passing (+19)

### Objectives
Wire the rule layer and the one implemented LLM agent (Coverage Validation) into a single orchestrator call, and implement the deterministic synthesis layer that produces a `RiskAssessment`. This is a **light** scope, deliberately narrower than the original four-agent Phase 7 plan: Documentation Review and Coding Validation are deferred (see Phase 6 above and `docs/Technical_Debt_Register.md` TD-04) rather than implemented as placeholders.

### Deliverables
- `rules/models.py`: `RiskAssessment` dataclass added — `score`, `findings`, `escalation_required`, `checks_run`
- `agents/orchestrator.py`: full implementation (light scope)
  - Runs the rule layer synchronously (`rules.rule_engine.review_claim()`); a HIGH NPI finding short-circuits before NCCI/MUE/code validity, exactly as it already did
  - If not short-circuited, calls the Coverage Validation Agent (the only implemented LLM agent) and includes it in `checks_run`
  - If short-circuited, the coverage agent is not called at all — `checks_run` has one entry (NPI)
  - Passes rule findings + coverage findings to `agents/denial_prevention.synthesize()` for deterministic scoring
  - Does not call, does not list in `checks_run`, and does not fabricate a placeholder finding for Documentation Review or Coding Validation
- `agents/denial_prevention.py`: full implementation (deterministic synthesis, no LLM call)
  - Combines rule findings + coverage findings, sorted HIGH → MEDIUM → LOW
  - `score` reuses `rules.rule_engine.overall_risk()` over the combined list
  - `escalation_required` is `True` when any finding's confidence is below `CONFIDENCE_REVIEW_THRESHOLD = 0.70` — the same threshold already used for the per-finding "Manual Review Recommended" caption in `app/main.py`
  - `checks_run` passed through unchanged from the orchestrator
- `app/main.py`: unified "🚀 Run Full Review" button (both Sample and Manual modes) — the recommended/default path; existing rule-layer-only "Review Claim" button preserved and relabeled, demoted from primary; `_render_full_review_results()` renders one consolidated findings list, an NPI short-circuit caption, the checks-run caption, and an escalation banner when `escalation_required` is true
- `tests/test_orchestrator.py`: full implementation, 11 tests, mocked Coverage Validation Agent (no real Anthropic calls)
- `tests/test_denial_prevention.py`: new, 8 tests, pure unit tests (no mocking needed — no I/O in `synthesize()`)

### Dependencies
- Phase 5 (Coverage Validation Agent v1/v2) complete

### Success Criteria
- A full review returns rule findings + coverage findings in one `RiskAssessment` ✅
- No fake or placeholder findings are generated for Documentation Review or Coding Validation ✅ (3 dedicated tests assert this)
- Audit workflow works unchanged for actual findings ✅
- UI supports a coherent one-click review flow ✅
- All 308 tests pass ✅

### Scope note (superseded by v1.3 — see Phase 7.5 below)
At the time this phase was scoped, Coding Validation was judged a non-goal as a separate LLM agent — doing so would duplicate the rule layer's NCCI/MUE/code_validity checks. v1.3 (Phase 7.5) revisited this: a Coding Validation Agent was implemented, scoped narrowly to reasoning the rule layer cannot perform (diagnosis specificity, coding defensibility, payer scrutiny risk), explicitly excluding NCCI/MUE/modifier/code-validity reasoning. See `docs/Architecture_Decisions.md` ADR-016. Documentation Review remains a deferred future capability (Phase 6 above), not an MVP blocker.

---

## Phase 7.5 — Coding Validation Agent (v1.3) ✅ Complete

**Tests:** 349 tests, all passing (+41)

### Objectives
Add a second LLM agent — Coding Validation — scoped to coding defensibility judgment the deterministic rule layer cannot make: diagnosis specificity, diagnosis-to-procedure support, payer scrutiny risk, and alternative diagnosis suggestions. Explicitly excludes NCCI edits, MUE limits, modifier requirements, and code validity — those remain rule-layer responsibilities.

### Deliverables
- `agents/coding_validation.py`: full implementation, mirroring `agents/coverage_validation.py`'s architecture exactly
  - `validate_coding(claim) -> list[Finding]`, one Anthropic call, forced `tool_choice`, `report_coding_finding`/`no_coding_concern` tool schema
  - Reuses the Coverage Agent's retrieval path unchanged (ChromaDB vector store first, JSON `policy_examples.json` fallback) — no new corpus, no new vector store
  - Same governance: no API key → `[]`; citation_doc_id not in retrieved set → suppressed finding; model exception → `[]`; stable `"cod-"`-prefixed finding IDs
- `agents/orchestrator.py`: calls `validate_coding()` sequentially after `validate_coverage()` (no parallel execution); adds the "Coding validation — LLM coding defensibility review" label to `checks_run`
- `agents/denial_prevention.py`: `synthesize()` grew a third `coding_findings` parameter, combined into `RiskAssessment` identically to coverage findings; scoring/escalation logic unchanged
- `app/main.py`: no changes — the existing `_render_full_review_results()` already renders any finding in `RiskAssessment.findings` generically; coding findings appear automatically through the Full Review path. The separate "Run AI Coverage Analysis" quick-check button remains Coverage-only by design.
- `tests/test_coding_validation.py`: new, 27 tests mirroring `test_coverage_validation.py` (finding present, no-concern path, citation grounding success/suppression, model exception, empty retrieval, vector/JSON fallback, excerpt cleanup — no real Anthropic calls)
- `tests/test_denial_prevention.py`: 4 new tests for coding findings in synthesis
- `tests/test_orchestrator.py`: extended to mock both agents; 10 net-new tests for coding-agent integration (called/not-called on short-circuit, checks_run label, score/escalation driven by coding findings, sequential call order)

### Dependencies
- Phase 7 (light orchestrator + synthesis) complete

### Success Criteria
- Full suite passes (349/349) ✅
- Coverage Agent behavior unchanged ✅
- Coding findings appear in Full Review and `RiskAssessment` ✅
- Deterministic synthesis remains intact (no LLM call in `denial_prevention.py`) ✅
- No governance regressions ✅
- No real Anthropic calls in tests ✅

### Scope note
Documentation Review Agent, an LLM-based Denial Prevention summary/narrative agent, parallel execution, and additional database tables were explicitly out of scope for this milestone and remain deferred. See `docs/Architecture_Decisions.md` ADR-016.

---

## Phase 8 — Evaluation Framework (v1.4) ✅ Complete

**Tests:** 375 tests, all passing (+26)

### Objectives
Build the golden-set evaluation infrastructure so that agent quality can be measured and regression-tested with precision.

### Deliverables
- `evaluation/golden_claims.json`: 14 synthetic claims (target 25, minimum 10 — expansion path is to append more claims to the same list; harness and tests need no changes) covering invalid NPI, NCCI conflict, MUE limit, missing modifier 25, diagnosis-to-procedure mismatch, Medicare coverage concern, coding defensibility concern, multi-finding, and clean scenarios, each with `claim_id` + `expected_findings` labels
- `evaluation/metrics.py`: maps `Finding.rule` → normalized label (the single place that vocabulary is defined); micro-averaged precision/recall/F1
- `evaluation/harness.py`: `run_evaluation()` calls `agents.orchestrator.run_review()` per claim. Offline by default — `agents.orchestrator.validate_coverage`/`validate_coding` are mocked to return `[]`, so no Anthropic call happens and the rule layer runs for real. `live=True` makes real agent calls (default model `claude-haiku-4-5`, the agents' own existing default) for a true read on agent-layer accuracy.
- `evaluation/run_evaluation.py`: CLI (`python -m evaluation.run_evaluation [--live]`), saves `latest_report.md` (metrics table + claim-level results), `latest_results.json`, `latest_summary.json` into `evaluation/`
- `tests/test_evaluation.py`: 26 new tests — label normalization, precision/recall/F1 (perfect match, false positive, false negative, empty/empty, both-empty-asymmetric, harmonic mean), evaluation runner behavior, no-API-call guarantee in offline mode
- No existing module's logic was modified — `agents/orchestrator.py` and `agents/denial_prevention.py` are called exactly as they are

### Deviation from original plan
Built as a standalone `evaluation/` module + CLI rather than a `pytest -m golden` marker — precision/recall against a golden set is a measurement to run and report on demand (and the only mode that's offline-safe is the rule-layer-only one), not a pass/fail gate suited to every `pytest tests/` run. See `docs/Technical_Debt_Register.md` TD-09 (resolved).

### Dependencies
- Phase 7.5 complete (Coding Validation Agent wired in)

### Results
- Offline (default, no API calls): Rule Engine 1.00 precision / 1.00 recall / 1.00 F1. Coverage/Coding Agent categories show 0.00 by design (mocked off) — not a quality measurement.
- Live (real `claude-haiku-4-5` calls, this v1.4 snapshot only — see Phase 8.7/v1.7 for the current numbers and current default model): Rule Engine still 1.00/1.00/1.00; Coverage Agent 0.30 precision / 1.00 recall; Coding Agent 0.25 precision / 1.00 recall — both agents catch every labeled positive but also flag several claims not labeled as agent-positive. Tracked as `docs/Technical_Debt_Register.md` TD-24, since partially resolved through Phases 1-3B in Phase 8.7/v1.7.

### Success Criteria
- Full suite passes (375/375) ✅
- Precision/recall/F1 computed overall and per category (Rule Engine, Coverage Agent, Coding Agent) ✅
- Saved evaluation report (markdown + JSON) ✅
- No real Anthropic calls in the automated test suite ✅
- 90%/85% precision/recall targets: met for Rule Engine offline; agent-layer live numbers not yet re-measured after the TD-24 Phase 1 label fixes (v1.7) — live re-run remains the recommended next step

---

## Phase 8.5 — ICD-10 Expansion (v1.5) ✅ Complete

**Tests:** 404 tests, all passing (+29)

### Objectives
Replace the hardcoded ICD-10 validation logic deferred since Phase 3 with a real ICD-10-CM reference dataset, closing the long-open gap noted there. Scope held tightly to code existence + description lookup + unspecified-diagnosis detection — no hierarchy reasoning, no new agents, no LLM calls.

### Deliverables
- `data/reference/icd10/icd10cm_order_2026.txt`: real CMS FY2026 ICD-10-CM order file (~98,000 codes), downloaded from `cms.gov`. Gitignored (matches the existing `data/reference/**/*.txt` pattern used by NCCI/MUE).
- `rules/icd10_loader.py`: file-backed fixed-width parser (mirrors `ncci_loader.py`/`mue_loader.py` conventions) with `lru_cache`; small synthetic fallback dict (`_SYNTHETIC_ICD10`, 10 codes) for portability when the CMS file isn't present (it's gitignored, like NCCI/MUE).
- `rules/icd10.py`: `check_icd10_validity(claim)` — two new rule types: `icd10_invalid` (HIGH, code not found in the dataset) and `icd10_unspecified` (MEDIUM, code found but its CMS description contains "unspecified" — a lookup-based signal, not hierarchy traversal).
- `rules/rule_engine.py`: new check appended to `CHECKS_RUN` and the `review_claim()` call sequence, after `code_validity`; respects the existing HIGH-NPI short-circuit. The pre-existing `dx_procedure_conflict`/`missing_modifier_25` rules in `code_validity.py` were left untouched.
- `evaluation/metrics.py`: two new normalized labels (`invalid_icd10_code`, `unspecified_diagnosis`) added to `RULE_LABELS`.
- `evaluation/golden_claims.json`: `GOLD-009` and `GOLD-011` updated — both use diagnosis codes (`J06.9`, `R10.9`) whose own CMS descriptions are unspecified, so the new rule-layer check now legitimately fires on them. `GOLD-009`'s `expected_findings` changed from `[]` to `["unspecified_diagnosis"]`; `GOLD-011` gained `"unspecified_diagnosis"` alongside its existing `"coding_defensibility"` label. Rule Engine offline precision/recall/F1 remains 1.00/1.00/1.00 after the update.
- `tests/test_icd10.py`: 29 new tests — file discovery, fixed-width parsing (fixture + real file), lookup, valid/invalid/unspecified/unknown code findings, duplicate-code de-duplication, citation structure, rule-engine integration (including the HIGH-NPI short-circuit still suppressing the new check).
- `tests/test_rule_engine.py`: `test_clean_claim_overall_risk_is_clean` switched from `J06.9` to `J02.0` (Streptococcal pharyngitis) — `J06.9`'s own CMS description is "Acute upper respiratory infection, unspecified," so it now correctly raises a MEDIUM finding and is no longer a valid "clean" fixture.

### Dependencies
- Phase 3 (deterministic layer) and Phase 8 (evaluation framework) complete

### Out of scope (deferred, not part of this phase)
Documentation Review Agent, deployment, Streamlit Cloud, public repo prep, LLM Denial Prevention Summary Agent, ICD-10 hierarchy reasoning, SNOMED mappings, CPT crosswalks, CMS claim editing engine, clinical decision support, diagnosis recommendations, root-cause grouping, deduplication, UI redesign.

### Success Criteria
- Full suite passes (404/404) ✅
- Rule engine validates ICD-10 codes from a real CMS reference dataset ✅
- Invalid codes flagged (HIGH) ✅
- Unspecified diagnoses flagged (MEDIUM) ✅
- Existing rule-engine behavior preserved (only `tests/test_rule_engine.py`'s fixture diagnosis code changed, not its assertions) ✅
- No new LLM calls; no orchestrator changes ✅

---

## Phase 8.6 — Public Release Hardening (v1.6) ✅ Complete

**Tests:** 426 tests, all passing (+22)

### Objectives
Harden the repository for eventual public release without deploying, going public, or adding product features. Close the gap between "works on the developer's machine with a real `.env`" and "works correctly on a fresh public clone with no API key at all."

### Deliverables
- Repository-wide hygiene pass: removed interview/hiring-manager/recruiter/UiPath framing from `docs/Demo_Script.md`, `docs/Demo_Script_Production_Validated.md`, `docs/Repository_Status_Report.md`, `docs/Roadmap.md`, `docs/Architecture_Decisions.md`; removed a personal-name authorship byline from `docs/Pre_Audit_Architecture_Review.md`. (Legitimate UX-research "user interviews" language and the LICENSE copyright line, which uses a GitHub handle, were left untouched — neither is a privacy or positioning issue.)
- `agents/orchestrator.py`: new `_ai_enabled()` gate checked before either agent is called — not just relying on each agent's own internal `if not api_key: return []` guard. Closes TD-12. `checks_run` now accurately omits the AI labels when no key is present.
- `app/main.py`: sidebar and in-page AI sections now show an explicit "⚠ AI Agents Disabled" warning (naming `ANTHROPIC_API_KEY`) instead of silently doing nothing.
- `data/synthetic/cached_ai_demo_artifacts.json` + `app/main.py:_render_cached_ai_demo()`: three sample claims (`CLM-001` multi-finding, `CLM-002` coding-only, `CLM-005` coverage-only) show pre-generated AI findings — captured from a real agent run — under a "📋 Pre-generated demonstration results" banner when AI is disabled. Read-only; never shown once a real key is present.
- `agents/run_logger.py`: structured local JSON-lines logging (`logs/agent_runs.jsonl`, gitignored) for each orchestrator-dispatched check — rule layer, coverage agent, coding agent — with timestamp, claim_id, agent, finding_count, success, latency_ms. Partially closes TD-16 (`AuditRepository` writes remain unlogged).
- `README.md` rewritten: portfolio/demo framing, "not for clinical or billing use" / "not HIPAA certified" disclosure, an explicit AI-features-are-optional section, and an Architecture Overview (Rule Layer / AI Layer / Orchestration / Evaluation).
- `docs/Demo_Script.md`: new "No-API-Key Demo Path" section covering the deterministic-only, invalid-NPI, NCCI/MUE/modifier, and ICD-10-unspecified scenarios, plus the cached-artifact claims, so a public user can exercise the whole app without a key.
- `docs/Technical_Debt_Register.md`: TD-12 closed, TD-16 marked partially resolved.
- New tests: `tests/test_app_ai_disabled.py` (5), `tests/test_cached_ai_demo.py` (9), `tests/test_run_logger.py` (4), plus 4 new `tests/test_orchestrator.py` cases for the no-key path.

### Out of scope (deferred, not part of this phase)
Streamlit Cloud deployment, switching the GitHub repository to public, LinkedIn/social content, Documentation Review Agent, LLM Denial Prevention Summary Agent, root-cause grouping, finding deduplication, new AI agents, major UI redesign.

### Success Criteria
- Fresh clone with no `ANTHROPIC_API_KEY` launches with no exception ✅
- Deterministic rule-engine review works fully without a key ✅
- Coverage and Coding agents are disabled, no Anthropic client is ever constructed ✅
- Cached AI demo scenarios are viewable without a key, clearly labeled as pre-generated ✅
- Full suite passes (426/426) ✅
- No personal names, recruiter/interview/LinkedIn/UiPath framing, secrets, or real PHI found in any tracked file (one residual flagged: the original PRD PDF cites two public UiPath press-release URLs as market-research sources — not edited, as it's the unmodified original product spec, not authored prose)

---

## Phase 8.7 — Quality Hardening Sprint (v1.7) ✅ Complete

**Tests:** 481 tests, all passing (+55 over the pre-sprint 426)

**Default AI model:** `claude-sonnet-4-6` (was `claude-haiku-4-5`; override with `ANTHROPIC_MODEL` — Haiku and Opus remain fully supported)

### Objectives
Close a small, deliberately scoped set of open technical-debt items without growing the agent count, building a full HCPCS reference-file platform, touching UI/UX, or doing any deployment/release work.

### Deliverables
- `docs/Technical_Debt_Register.md` TD-24 — **partially resolved** across four passes: Phase 1 (relabeled the two live "false positives" from the Phase 8 `--live` run, `GOLD-008`/`GOLD-009`, as plausible-but-unlabeled rather than over-flagging, and added `GOLD-015` as an explicit agent-negative baseline); Phase 2 (live re-measurement against the relabeled set, confirming precision improved); Phase 3 (anti-pile-on prompt calibration — overshot, recall dropped); Phase 3B (`rule_findings`-conditional narrowing — recovered recall while keeping precision gains, best F1 of all phases: Overall 0.92/0.85/0.88, Coverage 1.00/0.50/0.67, Coding 0.60/0.60/0.60). A follow-up Haiku-vs-Sonnet-vs-Opus live benchmark on the same Phase 3B prompts found Sonnet 4.6 had the best overall F1 (0.86) and was the only model scoring non-zero on both agents at once — `_DEFAULT_MODEL` was changed to `claude-sonnet-4-6` in both `agents/coverage_validation.py` and `agents/coding_validation.py` on that basis. Remaining gap: residual multi-finding pile-on/drop pattern, and the 15-claim golden set is still too small to be statistically significant (Future Work: expand to 30–50 claims).
- TD-26: `retrieval/chunking.py:is_low_information_excerpt()` catches grammatically-complete-but-boilerplate citation excerpts (e.g. "Scroll down for links..."); wired into both agents' `_clean_citation_excerpt()`.
- TD-06 (fully resolved): `rules/hcpcs.py` — a curated ~16-code HCPCS Level II recognition check (format regex + small dict, MEDIUM `hcpcs_unrecognized` finding); two new modifier rules in `rules/code_validity.py` (`missing_modifier_76` repeat-procedure, `missing_modifier_50` bilateral), bringing total active modifier rules to 3 (25, 76/77, 50).
- TD-15: `code_validity.py`'s citation `edition` strings changed from `"(sample reference)"` to `"(curated interpretive rule — not file-backed)"`, distinguishing permanently-hardcoded rules from genuine missing-CMS-file fallback scenarios.
- TD-20: `citation_excerpt` column added to `audit_decisions` (backward-compatible migration), threaded through `AuditDecision`, `save_decision()`, and `app/main.py`'s Save Decision handler.
- TD-27 (backend only): `rules/data_source_status.py` — aggregates the existing NCCI/MUE/ICD-10 loaders' discovery functions into `get_data_source_status()` / `any_synthetic_fallback_active()`. No UI indicator, per scope.
- New tests: 10 in `tests/test_rules.py`, 12 in `tests/test_hcpcs.py`, 6 in `tests/test_chunking.py`, 5 in `tests/test_data_source_status.py`, 3 in `tests/test_audit.py`, 14 across `tests/test_coverage_validation.py`/`tests/test_coding_validation.py` (TD-24 Phase 3/3B prompt + rule_findings-threading assertions).

### Out of scope (deferred, not part of this phase)
TD-22, TD-23, TD-25, Documentation Review Agent, LLM Denial Prevention Summary Agent, UI redesign/polish, deployment, Streamlit Cloud, public release tasks, expanding the golden set beyond 15 claims, and any further prompt calibration beyond Phase 3B.

### Dependencies
- Phase 8.6 complete

### Success Criteria
- Full suite passes (481/481) ✅
- TD-06, TD-15, TD-20, TD-26 fully resolved; TD-24 (Phases 1/2/3B) and TD-27 backend partially/fully resolved ✅
- Default live model upgraded to Sonnet 4.6 based on a live Haiku/Sonnet/Opus comparison ✅
- No UI, launch, or social-media content touched ✅

---

## Phase 8.8 — UI Polish & First-Time User Experience (v1.8a) ✅ Complete

**Tests:** 482 tests, all passing (+1 over the pre-sprint 481)

### Objectives
Improve first-impression quality for public reviewers, technical stakeholders, open-source visitors, and portfolio reviewers — without building new backend product functionality, touching agent prompts, or expanding scope into deployment.

### Deliverables
- Sidebar removed entirely; replaced with a header bar containing the reviewer name field and two status pills.
- **AI status pill** ("● AI: Enabled" / "● AI: Disabled") and **Data Source Status pill** ("Data: Live CMS" / "Data: Synthetic fallback" / "Data: Mixed") — the latter surfaces TD-27's backend status check (`rules/data_source_status.py`, v1.7) in the UI for the first time, closing the UI half of TD-27. Clicking the pill opens a popover with per-dataset (NCCI/MUE/ICD-10) status, version, and effective date. Cached at process lifetime (`st.cache_resource`), not a short TTL, since a cold real-data parse can be slow.
- Claim entry consolidated: the old "Sample Claim" / "Manual Claim Entry" tab split replaced with one "Claim Details" flow — a "Pick a demo scenario" / "Enter manually" radio, with a landing state and three recommended demo shortcuts shown only in demo mode.
- Demo scenarios tagged by type ("Rule Engine Demo" / "AI Demo" / "Rule + AI Demo") via an additive `demo_type` field in `data/synthetic/sample_claims.json`.
- "❔ Getting Started" onboarding dialog: how-it-works, architecture diagram, AI/demo-mode legend, confidence legend, limitations/disclaimers, About This Project, and full release history (v1.0–current).
- Finding cards gained a source badge (Rule Engine / Coverage Agent / Coding Agent, derived from the existing `Finding.rule` field — no schema change) and a plain-English "why this matters" line per rule type.
- Risk banner gained a severity-count "Why" breakdown and a "Recommended Action" line.
- Audit Trail's redundant "Export to CSV" button removed (the dataframe's native per-table download already covers it).
- Manual-entry Payer field defaults to Medicare (others still selectable) with a caption noting payer doesn't currently affect rule-layer findings or retrieval; Clinical Notes field kept visible (not collapsed) per explicit product decision.
- Two real bugs found and fixed during the polish pass: (1) "Clear Form" cleared `session_state` correctly but the browser kept showing stale field values — a Streamlit frontend quirk with deleted-but-not-replaced widget keys, fixed via versioned widget keys (`manual_claim_id_v{N}`, `sl_{N}_{row}_{field}`) that increment on every clear/template-load; (2) "Add Service Line" and the row "✕" remove button required two clicks to take visible effect, because neither called `st.rerun()` after mutating `session_state` — both now update on a single click.
- TD-25 re-investigated: considered widening `dx_procedure_conflict` to prefix-match the full Z00 family (matching `missing_modifier_25`'s existing behavior), but this regressed two calibrated golden-set tests (GOLD-005/GOLD-013 deliberately expect Z00.01 to raise only `missing_modifier_25`). Reverted; TD-25 remains deferred, now with a code comment and regression test documenting why.

### Out of scope (deferred, not part of this phase)
TD-22 (deferred to Phase 8.9/v1.8b), TD-23, deployment, Streamlit Cloud, public repo switch, new AI agents, backend quality hardening, prompt tuning, golden-set expansion.

### Dependencies
- Phase 8.7 complete

### Success Criteria
- Full suite passes (482/482) ✅
- Sidebar fully removed, replaced with header bar ✅
- TD-27 UI half resolved (data-source pill) ✅
- First-time-user onboarding (Getting Started dialog) shipped ✅
- No backend/agent logic changed (only the bounded, reverted TD-25 investigation) ✅

---

## Phase 8.9 — Citation Transparency (v1.8b) ✅ Complete

**Tests:** 488 tests, all passing (+6 over the pre-sprint 482)

### Objectives
Close TD-22 (retrieved policy transparency limited to one displayed citation) without changing governance rules, citation grounding, or `RiskAssessment`'s schema.

### Deliverables
- `agents/coverage_validation.py:validate_coverage()` and `agents/coding_validation.py:validate_coding()` now return `(findings, retrieved_policies)` instead of just `findings` — `retrieved_policies` is the same up-to-3 policy list each agent already retrieves internally via `_retrieve_policies()`, no longer discarded after the model call, no new retrieval or model call added.
- `agents/orchestrator.py:run_review()` returns `(RiskAssessment, retrieved_policies)` as a sibling tuple keyed by agent rule name (`"coverage_validation"`, `"coding_validation"`) — `RiskAssessment`'s own shape, and therefore the audit/DB layer, is unchanged.
- `app/main.py:_render_supporting_policies()` — a new "📚 Supporting Policies Reviewed (N)" expander on AI-sourced finding cards, listing other retrieved policies (title, section, effective date, excerpt) excluding the one already cited, explicitly captioned as "considered during AI analysis but not the basis for this finding" so it's never mistaken for additional evidence.
- All call sites updated: both full-review paths in `app/main.py`, the standalone "Run AI Coverage Analysis" button, `evaluation/harness.py` (including a real bug caught and fixed — the offline-mode mock returned a bare `[]`, which would have broken on the new tuple-unpacking), and `agents/run_logger.py`'s docstring example.
- 6 new tests across `tests/test_coverage_validation.py`, `tests/test_coding_validation.py`, and `tests/test_orchestrator.py` asserting the new return shape and content.

### Out of scope (deferred, not part of this phase)
TD-23 (dedup/root-cause grouping across agents) remains fully deferred — not attempted even in a small form.

### Dependencies
- Phase 8.8 complete

### Success Criteria
- Full suite passes (488/488) ✅
- TD-22 resolved ✅
- No change to citation grounding, governance rules, or `RiskAssessment`'s schema ✅

---

## Phase 9 — Portfolio Publication

**Status:** Future  
**Estimated scope:** 1 session

### Objectives
Make the repository publicly visible. Phase 8.6 (v1.6) already delivered the README rewrite, screenshots, and hygiene pass that this phase originally scoped — what remains is the act of going public.

### Deliverables
- GitHub repository set to public
- GitHub Actions CI (optional): `pytest tests/` on push to main

### Dependencies
- Phase 8.6 complete (hygiene, secret-safety, and README work done)
- No PHI in any committed file (verified)

### Success Criteria
- A new user can clone the repository, follow the README, and run the app with `streamlit run app/main.py` in under 5 minutes
- Screenshots clearly show the findings panel, citation display, audit trail, and export

---

## Phase 10 — Streamlit Cloud Deployment

**Status:** In progress — code readiness complete, deploy not yet attempted  
**Estimated scope:** 1 session  
**Tests:** 497 tests, all passing (+9 over the pre-work 488)

### Objectives
Deploy the application to Streamlit Cloud so it is accessible via a public URL without local setup.

### Deliverables
- ✅ `st.secrets` used instead of bare `os.getenv` for cloud deployment — `agents/secrets.py:get_secret()` checks the OS environment variable first (local `.env` via python-dotenv, unchanged behavior), then falls back to `st.secrets`, wrapped in `try/except` so a local run with no `.streamlit/secrets.toml` never crashes. Used for both `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` in `app/main.py`, `agents/orchestrator.py`, `agents/coverage_validation.py`, `agents/coding_validation.py`.
- ✅ `db/audit.db` path updated to use a temp directory — `db/audit_repository.py:DB_PATH` now defaults to `pathlib.Path(tempfile.gettempdir()) / "denial_copilot_audit.db"` instead of a path inside the repo; explicit `db_path` override (used by all tests) is unaffected. README documents that the audit trail is demo-local and may reset on hosted restarts.
- ✅ Fresh-clone validation performed (no `.env`, no API key, no local CMS datasets, no seeded Chroma store, no pre-existing `audit.db`, fresh venv from pinned `requirements.txt`) — app boots cleanly, AI-disabled path works, Chroma-empty-to-JSON-fallback retrieval chain works, synthetic-fallback data-source pill works, audit DB initializes from nothing. One benign cosmetic fix found and applied: removed a redundant `value=1` from the service-line `Units` `number_input` (`app/main.py`) that triggered a harmless Streamlit session-state warning when "Start from a template" populated it — `min_value=1` already supplies the same default, so behavior is unchanged.
- ✅ v1.9 follow-up: fixed a schema-initialization bug surfaced by the temp-dir audit DB path above — a long-running Streamlit process's cached `AuditRepository` (`@st.cache_resource`) only ran `initialize_database()` once per process, so a temp-dir file deleted by the OS mid-session and silently recreated empty on the next connect left the `audit_decisions` table missing, raising `sqlite3.OperationalError: no such table: audit_decisions` on every Audit Trail read thereafter. `db/audit_repository.py:_connect()` now re-applies the idempotent `CREATE TABLE IF NOT EXISTS` schema and migrations on every connection, so a brand-new or schema-missing DB file self-initializes on first use — including reads (`get_decisions()`, `export_decisions_csv()`), not just writes. 3 new regression tests in `tests/test_audit.py` cover a DB file present with no `audit_decisions` table for each of `get_decisions()`, `export_decisions_csv()`, and `save_decision()`.
- ⬜ `requirements.txt` verified against Streamlit Cloud's Python environment — pinned to locally-tested versions; not yet verified against an actual Cloud build
- ⬜ Streamlit Cloud secrets configured for `ANTHROPIC_API_KEY` — deploy-time action, not yet performed (no deploy attempted)
- ⬜ Live URL linked from GitHub README — pending the deploy itself

### Dependencies
- Phase 9 complete (repository is public and polished)
- Streamlit Cloud account

### Success Criteria
- The application loads at the Streamlit Cloud URL with no errors
- Synthetic claims can be reviewed; findings display correctly
- If agents are wired: a full review completes within 30 seconds
- Audit trail tab works (using session-scoped in-memory SQLite for cloud)

---

==================================================
## MVP V1 ACHIEVED
==================================================

**Implemented through:**
- v1.8a
- v1.8b
- v1.9

**Objectives achieved:**
- Core rule engine
- Coverage validation
- Coding validation
- Citation grounding
- Human review workflow
- Audit logging
- Deployment readiness
- Fresh clone validation

This milestone is the public-facing product designation — see `README.md`'s "Current Product Release" line and `docs/Repository_Status_Report.md`'s MVP V1 update for the current-state summary. The phase-by-phase history above (Phase 0 through Phase 10) is the detailed engineering record behind this milestone and is preserved as-is; this section does not supersede or rewrite it.

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
| 3 — Complete Deterministic Layer | ✅ MVP-complete | Phase A+B+Sprint 8 done (Units + MUE + NPI + UI); ICD-10-CM deferred | P0 |
| 4 — LCD/NCD Retrieval | ✅ Complete (1A–1D) | chunking, ChromaDB vector_store, CMS ingestion (TD-18 verified live), 44 new tests | P0 (dep) |
| 5 — Coverage Agent v1 | ✅ v1 complete | JSON-backed retrieval, structured tool use, citation grounding, 14 mocked tests (Sprint 9) | P0 |
| 5 — Option A corpus expansion | ✅ v1+ complete | 14 new LCD/NCD entries (18 total), 27 retrieval validation tests, 6 demo scenarios (Sprint 10) | P0 |
| 5v2 — Coverage Agent (ChromaDB) | ✅ Complete (Session 1D) | Vector-first retrieval with JSON fallback; index not pre-seeded | P0 |
| 6 — Documentation Agent | ⏸️ Deferred / Under Evaluation | Clinical note analysis — not an MVP blocker | P1 |
| 7 — Light Orchestrator + Synthesis | ✅ Complete (light scope) | Unified Review: rule layer + Coverage Agent → RiskAssessment, 308 tests | P0 |
| 7.5 — Coding Validation Agent (v1.3) | ✅ Complete | Second LLM agent: coding defensibility, diagnosis specificity, payer scrutiny risk; 349 tests | P0 |
| 8 — Evaluation Framework (v1.4) | ✅ Complete | Golden set, precision/recall harness; Rule Engine 1.00/1.00/1.00 offline; 375 tests | P0 metric |
| 8.5 — ICD-10 Expansion (v1.5) | ✅ Complete | Real CMS ICD-10-CM dataset; icd10_invalid/icd10_unspecified rules; 404 tests | P0 |
| 8.6 — Public Release Hardening (v1.6) | ✅ Complete | No-key safe mode, cached AI demo artifacts, repo hygiene, structured logging; 426 tests | Portfolio |
| 8.7 — Quality Hardening Sprint (v1.7) | ✅ Complete | HCPCS + modifier rules, citation excerpt persistence, real-data status check, TD-24 Phases 1-3B (prompt calibration), Haiku/Sonnet/Opus comparison → default model now Sonnet 4.6; 481 tests | P1 |
| 8.8 — UI Polish & First-Time UX (v1.8a) | ✅ Complete | Sidebar removed, header bar (AI + Data Source status pills), claim-entry consolidation, Getting Started onboarding, source badges, risk visualization, Clear Form + Add/Remove Service Line bug fixes; 482 tests | Portfolio |
| 8.9 — Citation Transparency (v1.8b) | ✅ Complete | TD-22 resolved: Supporting Policies Reviewed UI + retrieved_policies plumbing through both agents and the orchestrator; 488 tests | P1 |
| 9 — Portfolio Publication | 🔜 | Repo set to public, optional CI | Portfolio |
| 10 — Streamlit Cloud | 🟡 In progress | Code readiness complete (secrets helper, audit DB temp path); deploy + live URL pending; 497 tests | Portfolio |
