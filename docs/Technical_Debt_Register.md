# Technical Debt Register
## Denial Prevention Copilot

**Last updated:** June 2026
**Scope:** All known technical debt as of v1.3 (Coding Validation Agent — `agents/coding_validation.py` implemented, 349 tests passing) plus v1.2 UI validation findings

Priority definitions:
- **High** — blocks a P0 PRD requirement, a core demo scenario, or correct audit behavior
- **Medium** — limits demo quality, test coverage, or developer clarity without blocking the current sprint
- **Low** — polish, maintainability, or future-proofing that does not affect current behavior

---

## Resolved Debt

### Resolved Before or During Sprint 2

These items were identified before audit logging was implemented and resolved in the pre-audit model refactor.

| ID | Description | Resolution |
|---|---|---|
| ~~TD-R1~~ | `Finding.citation` was a flat `str`, could not map to 3-column DB schema | Replaced with `Citation` dataclass in pre-audit refactor |
| ~~TD-R2~~ | No stable finding identity across runs | Added `finding_id` via SHA-256 in `rule_engine._make_finding_id()` |
| ~~TD-R3~~ | Session state keys were positional (`decision_0`, `reason_0`) | Re-keyed to `decision_{finding_id}` — content-based, order-stable |
| ~~TD-R4~~ | Widget key reused as persistent storage slot for override reason | Split into `reason_input_{fid}` (widget) and `reason_{fid}` (storage) |
| ~~TD-R5~~ | No `source` field on `Finding` to distinguish rule vs. agent origin | Added `source: str = "rule_layer"` to `Finding` dataclass |

### Resolved in Sprint 3

| ID | Description | Resolution |
|---|---|---|
| ~~TD-R6~~ | Citation `doc_id` values were opaque synthetic strings (`"NCCI-PTP-SYNTHETIC"`, `"ICD10CM-FY2026"`, `"NCCI-POLICY-MANUAL"`) not traceable to any real document | Updated to stable, versioned doc_ids (`NCCI_PTP_80048_80053_SAMPLE` etc.) keyed to `policy_examples.json` entries |
| ~~TD-R7~~ | Citation detail view (excerpt only) had no policy title, source URL, or notes | Added `retrieval/policy_repository.py` and enriched `_render_citation_detail()` in `app/main.py` |
| ~~TD-R8~~ | `audit_decisions` table had no `citation_effective_date` column; effective dates in `Citation` were not persisted | Added column with backward-compatible `ALTER TABLE` migration in `initialize_database()` |

### Resolved in Sprint 4

| ID | Description | Resolution |
|---|---|---|
| ~~TD-07~~ | No manual claim intake — demo limited to 5 fixed synthetic claims | `app/claim_intake.py` + Manual Claim Entry mode in `app/main.py`; service-line coding grid, payer mapping, NPI format validation, Load Worked Example; `load_claim()` updated for backward compat |
| ~~TD-01~~ | Only 1 hardcoded NCCI PTP edit pair (of ~250,000+) | `rules/ncci_loader.py` loads all 4 CMS xlsx files; `rules/ncci.py` uses file-backed lookup with synthetic fallback; ~1.73M active pairs now available; 44 new tests |
| ~~TD-02~~ | `rules/mue.py` was a docstring-only stub | `rules/mue_loader.py` + `rules/mue.py` implemented; file-backed with synthetic fallback; MAI-aware severity; wired into rule engine; 35 new tests (Sprint 6) |
| ~~TD-03~~ | `rules/npi.py` was a docstring-only stub | `rules/npi.py` implemented with `luhn_valid()`, `lookup_nppes()`, `check_npi()`; HIGH for format/Luhn failure (short-circuits rule engine); MEDIUM for NPPES not found; no finding on timeout; 13 new tests (Sprint 7) |
| ~~TD-07b~~ | NPI Luhn check not in `validate_npi()` in `claim_intake.py` | Luhn validation now lives in `rules/npi.py:luhn_valid()` and fires as a rule engine check; `validate_npi()` UI function intentionally keeps format-only check to avoid blocking the manual entry form with synthetic demo NPIs |
| ~~TD-17~~ | Synthetic NPIs in `sample_claims.json` fail Luhn | All 5 sample claims updated: `npi` set to `""` (blank = optional); NPI validation skips empty NPIs by design |
| ~~TD-08~~ (partial) | `tests/test_rules.py` was a docstring stub | Implemented with 35 MUE, NCCI, and code_validity tests — TD-08 partially resolved; 13 NPI tests added in Sprint 7 (48 tests in test_rules.py); `test_orchestrator.py` remains a stub pending Phase 7 |

---

## Open Debt

### HIGH Priority

---

#### ~~TD-01: Only One Hardcoded NCCI PTP Edit Pair~~ — RESOLVED Sprint 5

**Resolution:** `rules/ncci_loader.py` loads all 4 CMS NCCI Practitioner PTP xlsx files (v322r0, effective 2026-07-01) from `data/reference/ncci/`. `rules/ncci.py` uses the file-backed lookup with a synthetic fallback when files are absent. ~1.73M active edit pairs now available. 44 new tests cover discovery, loading, lookup, and fallback behavior.

**Remaining note:** First load takes ~54s (xlsx reading); cached for process lifetime via `functools.lru_cache`. A future sprint could pre-serialize to pickle/parquet for faster startup if needed.

---

#### ~~TD-02: `rules/mue.py` Is a Docstring-Only Stub~~ — RESOLVED Sprint 6

**Resolution:** `rules/mue_loader.py` implements file-backed MUE table loading from `data/reference/mue/*.xlsx` (or `*.csv`) with column-name discovery (not fixed column positions), `functools.lru_cache`, and synthetic fallback when no CMS files are present. `rules/mue.py:check_mue_limits()` compares `claim.units[code]` against the MUE table; MAI=1 → HIGH, MAI=2/3 → MEDIUM. Wired into `rule_engine.review_claim()` after NCCI. 35 new tests cover all severity paths, fallback, file-backed loading (xlsx + csv), multi-code claims, and integration with rule engine.

Units field support added simultaneously: `build_manual_claim()` now populates `ClaimIn.units` from the service-line grid; UI grid has a Units column; `WORKED_EXAMPLE` includes `units` per service line.

**Remaining note:** CMS Practitioner Services MUE file must be downloaded separately and placed in `data/reference/mue/`. Until then, the synthetic fallback (`_SYNTHETIC_MUE` dict in `mue_loader.py`) provides plausible but non-authoritative limits for 7 common codes.

---

#### ~~TD-03: `rules/npi.py` Is a Docstring-Only Stub~~ — RESOLVED Sprint 7

**Resolution:** `rules/npi.py` fully implemented with three public functions:
- `luhn_valid(npi: str) -> bool` — Luhn check with "80840" prefix per CMS NPI specification.
- `lookup_nppes(npi: str) -> dict | None` — NPPES REST API client (v2.1), 2-second timeout; raises on network error.
- `check_npi(claim: ClaimIn) -> list[Finding]` — validates format, Luhn, then NPPES status.

Behavior: empty NPI → no finding (optional field); non-numeric or wrong length → HIGH; Luhn failure → HIGH; NPPES not found → MEDIUM; NPPES active → no finding; NPPES timeout/error → no finding (review never blocked). HIGH findings short-circuit the rule engine — NCCI/MUE/code_validity do not run when the NPI is structurally invalid. 13 new tests cover all paths including mock-based NPPES tests (no real network calls in tests). Sample claims updated: all NPIs set to "" to avoid demo noise.

---

#### TD-04: Most LLM Agents Still Stubs (Partially Resolved Sprint 9; Orchestrator + Synthesis Resolved Phase 7 light scope; Coding Validation Resolved v1.3)

**Resolution (Partial):** `agents/coverage_validation.py` is implemented as of Sprint 9. `validate_coverage(claim)` calls Claude via structured tool use, enforces citation grounding, and returns 0 or 1 `Finding` object. 14 mocked tests cover all governance paths. See ADR-012 for design decisions.

**Resolution (Phase 7, light scope):** `agents/orchestrator.py` and `agents/denial_prevention.py` are now implemented. `run_review(claim)` runs the rule layer, calls the Coverage Validation Agent when not short-circuited, and passes both finding sets to `denial_prevention.synthesize()` for a deterministic `RiskAssessment`. See ADR-015 for the scoping rationale (light orchestrator, two sources combined — not the original four-agent plan).

**Resolution (v1.3):** `agents/coding_validation.py` is now implemented, mirroring the Coverage Agent's architecture exactly (same retrieval, same citation-grounding/governance pattern, same error handling), scoped to reasoning the rule layer cannot perform (diagnosis specificity, coding defensibility, payer scrutiny risk). `agents/orchestrator.py` calls it sequentially after the Coverage Agent; `agents/denial_prevention.py:synthesize()` combines all three finding sources. See ADR-016 (supersedes ADR-015's "non-goal" framing for Coding Validation specifically; ADR-015 itself is left unchanged).

**Remaining:** `agents/documentation_review.py` still contains only a docstring. Documentation Review is **Deferred / Under Evaluation** — it remains part of the product vision (PRD §9) and the roadmap (`docs/Roadmap.md` Phase 6), to be revisited before public release, but is explicitly not required for the current MVP.

**Description:** `agents/documentation_review.py` contains a docstring describing intended behavior but no implementation.

**Location:** `agents/documentation_review.py`

**Impact:**
- Documentation review findings do not exist yet — by design for this milestone, not as an oversight. No placeholder finding is fabricated in its place (verified by dedicated tests in `tests/test_orchestrator.py`).
- The full four-agent PRD vision (§9) is not yet fully assembled; the orchestrator currently combines three sources (rules + coverage + coding), not four.

**Recommended Fix:**
- Phase 6 (when revisited, pre-public-release): Implement `documentation_review.py`, wire it into `agents/orchestrator.py` as an additional call before `denial_prevention.synthesize()`.
- All agents must use Anthropic SDK structured tool use with `claude-sonnet-4-6` (or claude-haiku-4-5 for lighter tasks).
- All agent findings must produce `Finding` objects conforming to the existing schema — no schema changes needed.

**Planned Sprint:** Phase 6 (deferred, revisit before public release)

---

#### TD-05: ChromaDB RAG Retrieval Pipeline Is Not Built — RESOLVED Phase 4 (Sessions 1A–1D)

**Original description:** `retrieval/ingest.py`, `retrieval/chunking.py`, and `retrieval/vector_store.py` were all docstring-only stubs. No LCD or NCD documents had been fetched from the CMS Coverage API or indexed in ChromaDB. The coverage agent could only reason over a curated 18-entry JSON corpus.

**Resolution:** All 5 originally recommended fix steps are now implemented, split across sessions to avoid stacking unverified layers:
1. `retrieval/ingest.py` (Session 1C, schema corrected in Session 1D per TD-18) — fetches LCDs/NCDs/Articles via the CMS Coverage API.
2. `retrieval/chunking.py` (Session 1A) — section-aware splitting.
3. `retrieval/vector_store.py` (Session 1B) — ChromaDB wrapper with `index()`/`query()`.
4. `agents/coverage_validation.py` (Session 1D) — now queries `vector_store` first; falls back to `find_policies_by_codes()` (JSON) only if the vector store is empty, returns nothing, or raises.
5. `scripts/ingest_coverage.py` (Session 1C) — CLI to populate `data/reference/coverage/` and, once run alongside `chunk_document()`/`VectorStore.index()`, the ChromaDB index.

**Remaining note:** The ChromaDB index is **not pre-seeded** — it starts empty in any fresh checkout or deployment. Until someone runs ingestion + chunking + indexing for a meaningful set of LCDs/NCDs, the coverage agent's vector path always returns nothing and every claim review uses the JSON fallback (which is exactly the same behavior as before this phase — no regression, just no improvement until seeded). Seeding a real corpus (beyond the tiny live-verification documents used in Session 1D, which were not persisted into a committed index) is intentionally out of scope for this phase per the session plan ("do not bulk-download CMS documents, do not seed a large ChromaDB corpus").

---

#### TD-06: Two Hardcoded Code Validity Rules (No Reference Files)

**Description:** `rules/code_validity.py` has two hardcoded rule tables: one ICD-10 conflict rule (Z00.00 vs. problem E/M) and one modifier rule (missing modifier 25). The production path requires loading from ICD-10-CM reference files and the NCCI Policy Manual.

**Location:** `rules/code_validity.py:_load_dx_procedure_rules()`, `_load_modifier_rules()`

**Impact:**
- Only Z00.00 triggers a dx-procedure conflict finding; hundreds of other diagnosis-to-procedure conflicts are silent.
- Only missing modifier 25 is checked; modifier 59, modifier 51, and other common modifier conflicts are undetected.
- `HCPCS Level II` validity (is this a real HCPCS code?) is not implemented.

**Recommended Fix:**
1. Load ICD-10-CM reference data from `data/reference/icd10cm_<FY>.csv` — replace `_load_dx_procedure_rules()` loader.
2. Load modifier rules from the NCCI Policy Manual guidance — expand `_load_modifier_rules()`.
3. Implement a HCPCS Level II validity check using the quarterly CMS HCPCS file.
4. Keep the public interface (`check_code_validity(claim)`) unchanged.

**Planned Sprint:** Phase 3 — Complete Deterministic Layer

---

### MEDIUM Priority

---

#### TD-07a: CSV Batch Upload Not Implemented

**Description:** Manual single-claim entry is live (Sprint 4), but batch review of an uploaded claim file (PRD §6 P1) is not yet built.

**Location:** `app/main.py` (Manual Claim Entry mode)

**Impact:**
- Cannot review more than one claim at a time without re-entering each manually.
- PRD P1 batch mode cannot be demonstrated.

**Recommended Fix:**
1. Add a "Upload CSV" option in Manual Claim Entry mode.
2. Validate CSV column headers (claim_id, payer, npi, cpt_codes, icd10_codes, modifiers, pos, units).
3. Iterate rows, call `build_manual_claim()` per row, render findings in a collapsible-per-claim layout.

**Planned Sprint:** Phase 3 extension

---

#### ~~TD-07b: NPI Luhn Check-Digit Validation Not Implemented~~ — RESOLVED Sprint 7

**Resolution:** Luhn validation now lives in `rules/npi.py:luhn_valid()` and fires as the first rule-engine check before NCCI/MUE. `validate_npi()` in `app/claim_intake.py` intentionally retains format-only check (10 digits, numeric) to avoid blocking the manual entry form when a user enters a synthetic or test NPI. The rule-layer Luhn check is the authoritative validation point; the UI form is a pre-flight hint only.

---

#### ~~TD-08: `tests/test_orchestrator.py` Remains a Stub~~ — RESOLVED Phase 7 (light orchestrator)

**Resolution:** `tests/test_orchestrator.py` is fully implemented — 11 tests, mocking `agents.orchestrator.validate_coverage` (the name orchestrator imports into its own namespace, matching the project's established mocking convention) rather than the Anthropic SDK directly, since `validate_coverage` is itself the unit boundary worth mocking at for this module. `tests/test_denial_prevention.py` was added alongside (8 tests, no mocking needed — `synthesize()` has no I/O). NPI rule tests were already added to `test_rules.py` in Phase B (Sprint 7), prior to this resolution.

**Planned Sprint:** Resolved Phase 7.

---

#### TD-09: Golden Set Evaluation Framework Not Implemented

**Description:** CLAUDE.md documents `pytest tests/ -m golden` as the command for golden-set precision/recall evaluation. The `golden` pytest marker, the golden fixture claims, and the evaluation assertions do not exist.

**Location:** `tests/` (missing), `data/synthetic/` (missing golden set)

**Impact:**
- Cannot measure finding precision or recall against the PRD targets (≥90% precision, ≥85% recall).
- Cannot demonstrate evaluation rigor in an AI PM or healthcare AI interview.
- No regression protection for agent quality as the system evolves.

**Recommended Fix:**
1. Create `data/synthetic/golden_claims.json` with 20–30 claims and their expected findings (known correct output).
2. Add `pytest.ini` configuration for the `golden` marker.
3. Implement `tests/test_golden.py` with assertions against precision and recall thresholds.
4. Run after every agent change.

**Planned Sprint:** Phase 8 — Evaluation Framework

---

#### TD-10: `db/audit.py` Stub Coexists with `audit_repository.py`

**Description:** `db/audit.py` is the original stub describing a four-table audit API (`write_claim`, `write_finding`, `write_decision`, `write_event`). It was superseded by `db/audit_repository.py` but was not removed.

**Location:** `db/audit.py`

**Impact:**
- Creates confusion: two files in `db/` purport to be the audit interface.
- `db/audit.py`'s API signature (`write_claim`, `get_claim_log`) does not match `AuditRepository`'s API.
- A developer new to the codebase would not know which one to use.

**Recommended Fix:**
- Option A: Delete `db/audit.py` and note in a CHANGELOG or commit message that it has been superseded.
- Option B: Convert `db/audit.py` into a roadmap comment pointing to `audit_repository.py` and describing when the multi-table design will be implemented.

**Planned Sprint:** Phase 3 cleanup

---

#### TD-11: `ClaimIn` Fields Are Untyped `list`

**Description:** `ClaimIn.cpt_codes`, `icd10_codes`, and `modifiers` are typed as bare `list` with no element type annotation. `units` is typed as `dict` with no key/value annotation.

**Location:** `rules/models.py:ClaimIn`

**Impact:**
- Type checkers cannot warn if a caller passes a list of integers instead of strings.
- No validation that ICD-10 codes match the expected format (e.g., "Z00.00") or that CPT codes are 5-digit strings.
- `load_claim()` in `rule_engine.py` passes values through without validation.

**Recommended Fix:**
```python
@dataclass
class ClaimIn:
    cpt_codes: list[str]
    icd10_codes: list[str]
    modifiers: list[str]
    units: dict[str, int]
```
Add boundary validation in `load_claim()` for format checks (5-digit CPT, ICD-10 pattern, valid POS codes).

**Planned Sprint:** Phase 3

---

#### TD-12: `ANTHROPIC_API_KEY` Guard (Partially Resolved Sprint 9)

**Resolution (Partial):** Sprint 9 added `load_dotenv()` at startup in `app/main.py`, the `_AI_ENABLED = bool(os.getenv("ANTHROPIC_API_KEY"))` flag computed at import time, and a sidebar warning ("AI Coverage Analysis disabled. Add `ANTHROPIC_API_KEY` to your `.env` file to enable.") when the key is absent. Coverage agent calls are gated on `_AI_ENABLED` — no SDK call is made if the key is missing. `.env.example` added to the repository with setup instructions.

**Remaining:** The sidebar warning is informational, not blocking. A user who has the key but has it set incorrectly (wrong format, revoked) will get a runtime error from the SDK when the AI button is clicked rather than a startup guard. Adding a key format validation at startup (`api_key.startswith("sk-ant-")`) would improve UX for this case.

**Planned Sprint:** Resolved for the no-key case; SDK-level key validation optional in a future sprint.

---

### LOW Priority

---

#### TD-13: `app/components/` Directory Is All Stubs

**Description:** Three UI component modules (`claim_form.py`, `findings_panel.py`, `audit_view.py`) exist as docstring-only stubs. All UI logic currently lives in `app/main.py`.

**Location:** `app/components/`

**Impact:**
- `app/main.py` will become unwieldy as more features are added.
- Low risk now (375 lines). Medium risk by Phase 5 (agents + retrieval adds complexity).

**Recommended Fix:** Extract UI sections into component modules as they are implemented:
- `claim_form.py`: when manual intake is built (Phase 3)
- `findings_panel.py`: when agent findings are added (Phase 5)
- `audit_view.py`: can be extracted now from the Audit Trail tab code

**Planned Sprint:** Incremental — extract during each phase as the related feature is built

---

#### TD-14: `requirements.txt` Lists Unused Dependencies

**Description:** `chromadb` and `pydantic` are in `requirements.txt` but are not imported by any implemented module. `chromadb` is for the vector store (stub); `pydantic` is for future `RiskAssessment` and orchestrator models.

**Location:** `requirements.txt`

**Impact:**
- Slower `pip install` for contributors who only need the rule layer.
- `chromadb` installs native dependencies (onnxruntime, etc.) that add several hundred MB.
- No functional impact on current code.

**Recommended Fix:** Either leave as-is (documents intent) or split into `requirements-dev.txt` (stubs/future) and `requirements.txt` (current runtime). Leave as-is is acceptable for a portfolio project.

**Planned Sprint:** Phase 4 (when chromadb is actually used)

---

#### TD-15: Citation Edition Is `"synthetic sample"` for Code Validity Rules

**Description:** NCCI PTP citations now use `edition = "v322r0"` and `effective_date = "2026-07-01"` from the real CMS files. However, `rules/code_validity.py` still uses `"ICD-10-CM FY2026 (sample reference)"` and `"NCCI Policy Manual for Medicare Services, effective January 2024 (sample reference)"`.

**Location:** `rules/code_validity.py`

**Impact:**
- NCCI findings are now fully traceable to the real CMS edition. ✅
- Code validity findings (Z00.00 dx conflict, modifier 25) still show synthetic edition labels.
- Low impact for demo; partially meaningful for governance claims.

**Recommended Fix:** When ICD-10-CM FY reference files are loaded in Phase 3, derive edition and effective_date from the file header and pass through to Citation.

**Planned Sprint:** Phase 3 (when ICD-10-CM reference files are loaded)

---

#### TD-16: No Application Logging

**Description:** The application has no structured logging. Errors from the rule engine, database operations, or (eventually) agent calls are not captured anywhere except the Streamlit error display.

**Location:** All modules

**Impact:**
- Debug information is lost between sessions.
- No way to audit rule engine behavior or diagnose intermittent errors.

**Recommended Fix:** Add Python `logging` at DEBUG level to rule modules and `AuditRepository`. One line per check run, one line per DB write. No need for a log aggregation service for a portfolio project.

**Planned Sprint:** Phase 5 (before agents generate meaningful logs)

---

#### ~~TD-17: Synthetic NPIs Do Not Pass Luhn Validation~~ — RESOLVED Sprint 7

**Resolution:** All 5 sample claims updated in `data/synthetic/sample_claims.json`: `npi` set to `""` (empty string). Empty NPI is treated as omitted — `check_npi()` returns no findings for blank NPIs. This avoids noisy NPI findings during demo when the focus is on NCCI/MUE/code validity. NPI can be demonstrated separately via manual claim entry with a deliberate invalid NPI.

---

#### TD-18: CMS Coverage API Field Names — RESOLVED (Verified Live) Session 1D

**Original description:** `retrieval/ingest.py:normalize_lcd/_ncd/_article()` mapped raw CMS Coverage API JSON fields into the internal document contract based on documentation conventions, not a live response — outbound network access was unavailable when this module was first built (Phase 4, Session 1C).

**Resolution:** Live network access was available at the start of Session 1D. Made real calls against `https://api.coverage.cms.gov` (LCD id `33797`, NCD id `108`, Article id `52514`) and corrected `retrieval/ingest.py` against the actual schema. Verified, in order:

1. **Response envelope.** Every data endpoint wraps its payload as `{"meta": {...}, "data": [{...}]}` — a one-element list, even for a single-document lookup. The original code assumed a flat dict; this was a real bug, not just an unverified guess, and is fixed via `_extract_record()`.
2. **Endpoint paths.** Corrected from assumed paths to verified ones:
   - LCD: `GET /v1/data/lcd?lcdid={id}` (assumed `/v1/data/lcd/{id}` — wrong, returned 401 for the wrong reason initially, then 400 "You must include a lcdid" once path-only was tried without the query param)
   - NCD: `GET /v1/data/ncd?ncdid={id}` (assumed `/v1/reports/national-coverage-ncd/{id}` — that path is actually a *list* report endpoint, not a per-document detail endpoint; it returns all 345 NCDs with only summary fields)
   - Article: `GET /v1/data/article?articleid={id}` (assumed `/v1/data/article/{id}` — same path-vs-query-param issue as LCD)
3. **Authentication.** LCD and Article endpoints require an `Authorization: Bearer` token, confirmed via live 401 without one. The token is obtained by simply calling `GET /v1/metadata/license-agreement` (no explicit "accept" step) and is valid ~1 hour. NCD requires no token (confirmed: 200 with no `Authorization` header). This was not implemented at all pre-Session-1D — a real functional gap, now fixed via `_get_license_token()`.
4. **Field names**, confirmed against live records:
   - LCD: `lcd_id`, `title`, `indication`, `diagnoses_support`, `diagnoses_dont_support`, `coding_guidelines`, `doc_reqs`, `bibliography`, `rev_eff_date`/`orig_det_eff_date`. (Assumed `indication_limitation`, `documentation_requirements`, `original_effective_date` — all wrong.)
   - NCD: `document_id`, `title`, `effective_date`, `implementation_date`, `item_service_description`, `indications_limitations`, `other_text`, `ama_statement`, `reasons_for_denial`. (`indications_limitations` happened to match one of the original guesses; the rest did not.)
   - Article: `article_id`, `title`, `article_eff_date`, `description`, `other_comments`, `icd9_covered_para`, `icd9_noncovered_para`. (Assumed `contractor_name`/`original_effective_date` — wrong field names for this document type.)
5. **Contractor is not a field on the LCD/Article record at all.** It's a separate sub-resource endpoint (`/v1/data/lcd/contractor?lcdid={id}&ver={version}`, confirmed live) returning a `contractor_id` integer, not a name — a further lookup against a contractor reference table would be needed to get a human-readable name. Out of scope for this sprint; `contractor` is left as `None` for LCD and Article (previously a guessed field name that would have silently returned `None` anyway, so behavior is unchanged, but the reason is now accurate).
6. **Text fields are double HTML-entity-encoded** (e.g. `&amp;ldquo;` decodes to `&ldquo;` on one pass, to a real curly quote only on a second pass) and contain HTML tags. Added `_clean_html()` (repeated `html.unescape()` + tag stripping) — not previously anticipated at all.
7. **Dates are `"MM/DD/YYYY"` strings**, not ISO-8601 as originally assumed. No format conversion is performed; documented as a known characteristic, not a bug, since `Citation.effective_date` is a free-form `Optional[str]`.

All three `fetch_*()` functions were re-run live end-to-end through `chunk_document()` and `VectorStore.index()`/`.query()` after the fix, confirming the full ingestion → chunking → indexing pipeline works against real CMS data, not just mocks.

**Verification artifact:** `tests/test_ingest.py` was rewritten (17 tests, up from 15) to mock the *verified* envelope/auth/field shape rather than the original guess, including a dedicated test for the double-HTML-entity-decoding behavior and the empty-`data`-list case.

**Remaining gap (downgraded, not closed):** Article and NCD section-field coverage was confirmed against exactly one live record each; other LCDs/NCDs/Articles may populate additional or different optional fields not in `_LCD_SECTION_FIELDS`/`_NCD_SECTION_FIELDS`/`_ARTICLE_SECTION_FIELDS`. This is a normal "schema has more sections than our display-heading map covers" gap, not an unverified-guess gap — `_extract_sections()` still degrades gracefully (skips unmapped fields) rather than failing.

---

#### TD-19: LCD/Article Contractor Name Not Populated (Sub-Resource Lookup Required)

**Description:** Confirmed live during TD-18 verification: `contractor` is not a field on the LCD or Article detail record. CMS exposes it via a separate sub-resource endpoint (`/v1/data/lcd/contractor?lcdid={id}&ver={version}` for LCDs, presumably an analogous endpoint for Articles) that returns a `contractor_id` integer — a further lookup against a contractor reference table (not yet identified) would be needed to resolve that to a human-readable name like "Noridian".

**Location:** `retrieval/ingest.py:normalize_lcd()`, `normalize_article()` — both hardcode `contractor: None`.

**Impact:** Citations built from live-ingested LCD/Article chunks never show a contractor name (the JSON `policy_examples.json` corpus, by contrast, has curated contractor names like "Noridian" set by hand). Low impact — `contractor` is not used in citation grounding or any governance check, only in display.

**Recommended Fix:** Call the `/v1/data/lcd/contractor` sub-resource after the main LCD fetch, then resolve `contractor_id` against CMS's contractor reference table (likely another Coverage API endpoint, not yet located) or a small static lookup table for the contractor IDs actually seen.

**Planned Sprint:** Low priority — revisit if a real demo needs contractor names displayed for live-ingested documents specifically.

---

#### TD-20: Raw AI Tool-Call Payloads and `citation_excerpt` Are Not Persisted

**Description:** Discovered while tracing a citation-excerpt question back through the pipeline (Phase 4, post-Session 1D). `db/audit_repository.py`'s `audit_decisions` table has no `citation_excerpt` column, and no module logs the raw Anthropic tool-call response (`report_coverage_finding`'s full `input` dict) anywhere — not to the audit log, not to `logger`, not to any file. Once a decision is saved, the `Citation.excerpt` text the reviewer actually saw is gone; it cannot be reconstructed from the database, only re-derived (approximately) by re-running retrieval against the same codes and guessing which sentence the model might have quoted.

**Location:** `db/audit_repository.py` (schema has no excerpt column), `agents/coverage_validation.py:_parse_response()` (constructs but never logs the raw tool-call `args` dict).

**Impact:**
- Cannot audit, in retrospect, exactly what supporting text the model cited for a given saved decision — only the doc_id/section/effective_date survive, not the excerpt itself.
- Investigating a disputed or confusing finding after the fact requires re-running the agent and hoping retrieval + model sampling reproduce the same excerpt; they may not, since `_clean_citation_excerpt()`'s fallback path and model sampling variance both mean two runs against the same chunk can legitimately choose different (both valid) supporting sentences.
- Related to, but distinct from, TD-16 (no application logging generally) — this is specifically about a governance/citation-integrity gap, not just missing debug logs: the "no citation → no finding" rule's evidentiary trail is incomplete once persisted.

**Recommended Fix:**
1. Add a `citation_excerpt` column to `audit_decisions` (with a backward-compatible `ALTER TABLE` migration, following the same pattern used for `citation_effective_date` in `initialize_database()`).
2. Pass `finding.citation.excerpt` through to `save_decision()` and persist it.
3. Optionally, log the raw tool-call `args` dict at DEBUG level in `_parse_response()` (ties into TD-16) for cases where even more than the final excerpt is needed for debugging.

**Planned Sprint:** Unscheduled — low effort (one column + one migration), worth doing whenever `db/audit_repository.py` is next touched.

---

#### TD-21: `VectorStore` Singleton Goes Stale If the Index Is Re-Built by a Separate Process

**Description:** Discovered while diagnosing why a freshly-seeded ChromaDB index still produced JSON-fallback citations in the running app (post-Session 1D). `agents/coverage_validation.py:_get_vector_store()` caches a single `VectorStore` instance for the lifetime of the Python process (`_vector_store_instance`). If that instance is constructed against an empty collection (no HNSW vector-index segment on disk yet) and a *separate* process later writes chunks into the same `retrieval/chroma_db/` directory, the original process's collection handle does not pick up the new segment. `count()` correctly reflects the new on-disk row count (a simple read), but `query()` raises `chromadb.errors.InternalError: Error executing plan: Internal error: Error creating hnsw segment reader: Nothing found on disk`. `_retrieve_from_vector_store()`'s broad `except Exception` catches this, logs a warning, and silently falls back to JSON — so the symptom looks like "the vector path isn't working" rather than a clear error.

**Location:** `agents/coverage_validation.py:_get_vector_store()`, `_vector_store_instance` module-level singleton; root behavior is inside `chromadb`'s embedded HNSW segment implementation, not this codebase.

**Impact:**
- After running `scripts/ingest_coverage.py` + chunking + indexing while the Streamlit app is already running, the app must be **manually restarted** to see the newly seeded documents — there is no in-app way to refresh the vector store.
- The failure mode is silent: the UI just keeps showing JSON-sourced citations with no visible error, since the exception is caught and logged (not surfaced to the UI) by design (consistent with the project's "infrastructure failure never blocks review" pattern — see ADR-013).
- Reproduced and confirmed in an isolated `/tmp` experiment: a `VectorStore` handle built against an empty collection, then a second process indexes data, then the *original* handle's `query()` fails with the exact same error message captured live in the running app's log.

**Recommended Fix:**
1. Operational (no code change): always restart the Streamlit process after running ingestion/indexing. Document this in a short runbook note (README or Roadmap).
2. Code-level: in `_retrieve_from_vector_store()`, catch this specific error (or any `query()` exception) and retry once against a freshly-constructed `VectorStore` (reset `_vector_store_instance = None`, rebuild, retry `query()`) before falling back to JSON — so a long-running process self-heals after an out-of-process re-index instead of requiring a manual restart.

**Planned Sprint:** Unscheduled — operational workaround (restart) is sufficient for the portfolio/demo use case; the self-healing retry is a nice-to-have if this app is ever deployed somewhere restarts aren't trivial (e.g. Streamlit Cloud with a long-lived session).

---

#### TD-22: Retrieved Policy Transparency Limited to One Displayed Citation

**Severity:** LOW / MEDIUM

**Observation:** During v1.2 UI validation, Test 1 returned a valid real CMS citation, but only one cited policy was displayed. The vector retriever may retrieve both LCD 33431 (HbA1c) and NCD 98 (Blood Glucose Testing), but the UI currently shows only the model-selected primary citation.

**Impact:** This does not block MVP correctness because the finding is still grounded in a retrieved CMS document. However, it limits retrieval transparency and makes it harder to show all policies considered during AI analysis.

**Recommended Fix:** Display "Supporting Policies Reviewed" separately from the primary citation, including `document_id`, title, section, and effective date for the top retrieved chunks.

**Status:** Deferred. Not required for v1.2 or v1.3 public portfolio readiness.

---

## Debt Summary

| Priority | Count | Resolved | Open |
|---|---|---|---|
| High | 11 | 11 (R1–R5, TD-01, TD-02, TD-03, TD-05, TD-08, TD-18) | 1 (TD-04 partial, TD-06 — see note) |
| Medium | 8 | 3 (TD-07, TD-07b, TD-08) | 5 (TD-07a, TD-09, TD-10, TD-11, TD-12, TD-21) |
| Low | 8 | 1 (TD-17) | 7 (TD-13, TD-14, TD-15, TD-16, TD-19, TD-20, TD-22) |
| Sprint 3 additions | 3 | 3 | 0 |
| **Total** | **30** | **19** | **11** |

Note: TD-04 (most LLM agents still stubs) is now further resolved — orchestrator and denial_prevention are implemented (Phase 7, light scope), and the Coding Validation Agent is now implemented (v1.3, ADR-016). Only Documentation Review (deferred, not a blocker) remains open under TD-04. TD-06 (two hardcoded code validity rules) remains fully open — neither was touched this phase. TD-08 (`test_orchestrator.py` stub) is now fully resolved.

Items R1–R5 were addressed in the pre-audit model refactor and Sprint 2.
Items R6–R8 were addressed in Sprint 3 (policy intelligence foundation).
TD-07 was addressed in Sprint 4 (manual claim intake); replaced by TD-07a (CSV batch) and TD-07b (Luhn NPI).
TD-01 was addressed in Sprint 5 (file-backed NCCI PTP lookup).
TD-02 was addressed in Sprint 6 (MUE ingestion + units field support). TD-08 partially resolved (test_rules.py filled in; test_orchestrator.py still a stub).
TD-03, TD-07b, TD-17 were addressed in Sprint 7 (NPI validation — Phase B). 13 new NPI tests. Sample claim NPIs blanked. `test_rules.py` now has 48 tests. Inline claim dicts in `test_rule_engine.py` and `test_policy_repository.py` updated from placeholder NPIs to `""`. Total tests: 183 passing.
The remaining open High items (TD-04, TD-05, TD-06) represent the core gap: LLM agents, RAG pipeline, and extended code validity rules.

**Sprint 3 note:** Local policy intelligence was introduced using curated public-policy-style references (`data/reference/policy_examples.json`). This makes the citation detail view evidence-backed without requiring CMS API automation, Chroma, or LLM calls. Real CMS/NCCI/LCD/NCD ingestion remains a future replacement point — `retrieval/policy_repository.py` is designed with the same public interface the ChromaDB-backed version will implement.

**Sprint 4 note:** Manual Claim Entry mode is live. Transformation logic (`build_manual_claim`, `get_payer_id`, `validate_npi`, `normalize_code`) lives in `app/claim_intake.py` with no Streamlit dependency, fully unit-tested (28 new tests). The service-line coding grid accepts arbitrary CPT/ICD-10/modifier combinations and flows through the existing rule engine unchanged. Remaining claim intake gaps: CSV batch upload (TD-07a) and Luhn NPI check-digit validation (TD-07b).

**Sprint 5 note:** File-backed NCCI PTP lookup implemented via `rules/ncci_loader.py`. Loads all 4 CMS Practitioner PTP xlsx files (v322r0, effective 2026-07-01) from `data/reference/ncci/` and caches ~1.73M active edit pairs in memory. First load takes ~54 seconds (xlsx reading); subsequent lookups are O(1). Synthetic fallback retained for portability when CMS files are absent. MUE ingestion is intentionally deferred to Phase 3 — only PTP edits are implemented in this sprint.

**Sprint 6 note:** MUE ingestion and units field support implemented (Phase A of the implementation plan). `rules/mue_loader.py` follows the `ncci_loader.py` pattern: file-backed loader from `data/reference/mue/` with column-name discovery, `lru_cache`, and synthetic fallback. `rules/mue.py:check_mue_limits()` returns MAI-aware findings (MAI=1 → HIGH, MAI=2/3 → MEDIUM). Units field support: `build_manual_claim()` now populates `ClaimIn.units`; service-line grid has a Units column; `WORKED_EXAMPLE` updated. 35 new tests added in `tests/test_rules.py` (previously a stub). Total tests: 165 passing. TD-02 resolved. TD-08 partially resolved.

**Sprint 7 note:** NPI validation implemented (Phase B). `rules/npi.py` implements `luhn_valid()` (Luhn with "80840" prefix), `lookup_nppes()` (NPPES REST API v2.1, 2-second timeout), and `check_npi()` (wired into rule engine as the first check, before NCCI/MUE/code_validity). HIGH findings (format/Luhn failure) short-circuit the rule engine. NPPES timeout and network errors are silenced — review continues. 13 new NPI tests in `test_rules.py` (all mocked; no real network calls). `data/reference/policy_examples.json` includes `NPPES_NPI_REGISTRY` citation anchor. Sample claims updated: all NPIs blanked to avoid demo noise. TD-03, TD-07b, TD-17 resolved. Total tests: 183 passing.

**Sprint 8 note:** UI/UX hardening. (1) `rules/rule_engine.py` now exports `CHECKS_RUN: list[str]` — a human-readable list of all 5 active checks in execution order, consumed by the UI. (2) `app/main.py` updated: checks-run caption now always visible after review (not just on CLEAN claims); NPI short-circuit detected and surfaced as `"⚡ NPI short-circuit"` message; sample-mode NPI blank now shows "Not provided" instead of empty field; sample-mode Review Claim button now has an explicit `key`; NPI field `help` text clarifies that Luhn runs at review time. (3) `.streamlit/config.toml` created with `primaryColor = "#1d4ed8"` — Review Claim button now renders blue (neutral primary action) instead of the Streamlit default red. (4) 3 new tests in `test_rule_engine.py` covering CHECKS_RUN structure, rule coverage, and NPI short-circuit engine behavior. Total tests: 186 passing.

**Phase 4 Session 1D note:** Coverage Agent v2 retrieval swap. Before coding, made live calls against `api.coverage.cms.gov` to validate the TD-18 field-name assumptions from Session 1C — found and fixed a real bug (responses are wrapped in a `{"meta", "data": [...]}` envelope, not flat dicts), corrected all three endpoint URLs, added the previously-missing Bearer token flow for LCD/Article, corrected every guessed field name against live records, and added double-HTML-entity cleanup. TD-18 resolved; new TD-19 opened for the (low-priority, display-only) contractor-name gap. `agents/coverage_validation.py` now queries `vector_store` first (`_retrieve_from_vector_store()`), falling back to the JSON `policy_repository` (`_retrieve_from_json_fallback()`) when the vector store is empty, returns nothing, or raises — `_retrieve_policies()` is the single entry point encoding that order. Tool schema, citation grounding, audit workflow, and UI are unchanged; all coverage-agent tests mock `_get_vector_store()` so no real ChromaDB is touched. TD-05 (ChromaDB RAG pipeline not built) resolved — all 5 of its original fix steps are now implemented across Sessions 1A–1D, though the index is not pre-seeded with a real corpus (intentionally, per the session's no-bulk-download constraint), so the JSON fallback remains the active path until someone runs ingestion against a real set of LCDs/NCDs. 24 tests in `test_coverage_validation.py` (up from 14), 17 in `test_ingest.py` (rewritten from 15 against the corrected schema). Total tests: 277 passing.

**Phase 4 Session 1D follow-up note (excerpt cleanup + live validation):** After Session 1D shipped, seeded a minimal real corpus (2 documents — LCD 33431 "HbA1c", NCD 98 "Blood Glucose Testing" — fetched live, not committed; `data/reference/coverage/` and `retrieval/chroma_db/` are both gitignored, so this seeded state is local-only and a fresh clone starts with an empty index) to validate the vector path end-to-end with a real Anthropic call. This surfaced two real bugs, both fixed:

1. **Dangling-fragment chunk boundaries.** `retrieval/chunking.py`'s long-paragraph fallback cut text at a fixed character offset rather than a sentence boundary, producing chunks like `"). This NCD lists the ICD-10 codes..."`. Fixed by replacing the hard character split with sentence-boundary-aware splitting (`_split_long_paragraph()`), plus defensive entity/tag cleanup and post-split trimming of any leading dangling punctuation/quote (`starts_with_dangling_fragment()`, `trim_leading_fragment()`, now public). `agents/coverage_validation.py` also gained `_clean_citation_excerpt()` as a second line of defense: if the model's own `citation_excerpt` still starts with a dangling fragment, it falls back to a cleaned, sentence-bounded snippet of the actual retrieved chunk rather than surfacing the fragment. 12 new tests (6 in `test_chunking.py`, 6 in `test_coverage_validation.py`). Total tests: 289 passing. Committed as `b92e8d7`.
2. **Stale `VectorStore` singleton after external re-indexing** (TD-21, new). Diagnosed by reproducing the exact `"Error creating hnsw segment reader: Nothing found on disk"` error in an isolated experiment and confirming it matched the running app's own log output. Root cause: the Streamlit process's cached `_vector_store_instance` was constructed against an empty collection before a separate process seeded it; ChromaDB's embedded HNSW reader doesn't pick up segments written after the handle was created. Workaround applied: restart the Streamlit process after running ingestion/indexing. No code fix applied this round — tracked as TD-21 with a self-healing-retry option for later.

Separately investigated (no bug found): traced why two different live runs displayed two different sentences from the same retrieved chunk as `citation_excerpt` — confirmed this is the model selecting a sub-span of the full chunk it was given (intended tool-use behavior, the schema asks for a supporting excerpt, not the whole chunk), not truncation in chunking, retrieval, or cleanup. This investigation surfaced TD-20 (raw tool-call payloads and `citation_excerpt` are never persisted, so a saved decision's literal excerpt can't be reconstructed after the fact).

**Phase 7 note (light orchestrator / Unified Review):** `agents/orchestrator.py` and `agents/denial_prevention.py` implemented against a deliberately light scope — combine the rule layer and the Coverage Validation Agent (the only implemented LLM agent) into one `RiskAssessment`, rather than the original four-agent plan. Documentation Review is explicitly deferred (marked "Deferred / Under Evaluation" in `docs/Roadmap.md`, not removed from the product vision) and Coding Validation is not planned as a separate LLM agent at all — see ADR-015 for the full rationale. No placeholder finding is fabricated for either; 3 dedicated tests in `tests/test_orchestrator.py` guard against this regressing. `RiskAssessment` added to `rules/models.py` as a plain dataclass (DEFER-003 resolved — Pydantic was considered and rejected since the object never crosses a serialization boundary in this scope). TD-04 partially resolved, TD-08 fully resolved. `app/main.py` gained a unified "🚀 Run Full Review" button (both Sample and Manual modes) as the recommended default path, alongside the existing rule-layer-only "Review Claim" button (preserved, relabeled, demoted from primary). 19 new tests (11 in `test_orchestrator.py`, 8 in `test_denial_prevention.py`, all mocking `agents.orchestrator.validate_coverage` — no real Anthropic calls in the suite). Total tests: 308 passing.

**v1.3 note (Coding Validation Agent):** `agents/coding_validation.py` implemented, mirroring `agents/coverage_validation.py`'s exact architecture (same vector-store-first/JSON-fallback retrieval, same forced-tool-choice two-tool schema, same citation-grounding and error-handling pattern) — see ADR-016. Scoped narrowly to reasoning the rule layer cannot perform (diagnosis specificity, diagnosis-to-procedure support, coding defensibility, payer scrutiny risk); the system prompt explicitly instructs the model to assume NCCI/MUE/modifier/code-validity checks are already done. `agents/orchestrator.py` calls it sequentially after the Coverage Agent (no parallel execution); `agents/denial_prevention.py:synthesize()` grew a third `coding_findings` parameter. ADR-015 is left unchanged per its "non-goal" framing being superseded, not rewritten, by ADR-016. TD-04 further resolved — only Documentation Review remains open under it. `tests/test_orchestrator.py`'s `test_no_coding_validation_placeholder_finding_ever_appears` (a Phase 7 regression guard against a fabricated Coding Validation finding) was removed since Coding Validation is now a real, implemented agent; superseded by real coverage in `tests/test_coding_validation.py` and new orchestrator-integration tests. 41 new tests (27 in `test_coding_validation.py`, 4 in `test_denial_prevention.py`, 10 net new in `test_orchestrator.py`). Total tests: 349 passing.
