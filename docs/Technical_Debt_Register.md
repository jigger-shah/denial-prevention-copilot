# Technical Debt Register
## Denial Prevention Copilot

**Last updated:** June 2026
**Scope:** All known technical debt as of Sprint 8 (UI/UX hardening — checks-run metadata, button styling, NPI display)

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

#### TD-04: All LLM Agents Are Docstring-Only Stubs

**Description:** `agents/coding_validation.py`, `agents/coverage_validation.py`, `agents/documentation_review.py`, `agents/denial_prevention.py`, and `agents/orchestrator.py` all contain docstrings describing their intended behavior but no implementation.

**Location:** `agents/` (all files)

**Impact:**
- The LLM-powered value proposition of the product cannot be demonstrated.
- Medical necessity findings (the coverage agent's output, and the most complex reasoning task) do not exist.
- Documentation review findings do not exist.
- The PRD's core agentic architecture (§9) is entirely unimplemented.
- Readiness scores for AI PM interview and Healthcare AI Governance demo are capped by this gap.

**Recommended Fix:**
- Phase 5: Implement `coverage_validation.py` first (highest-value, highest-difficulty reasoning task).
- Phase 6: Implement `documentation_review.py`.
- Phase 7: Implement `orchestrator.py` and `denial_prevention.py`.
- All agents must use Anthropic SDK structured tool use with `claude-sonnet-4-6`.
- All agent findings must produce `Finding` objects conforming to the existing schema — no schema changes needed.

**Planned Sprint:** Phases 5–7

---

#### TD-05: RAG Retrieval Pipeline Is Not Built

**Description:** `retrieval/ingest.py`, `retrieval/chunking.py`, and `retrieval/vector_store.py` are all docstring-only stubs. No LCD or NCD documents have been fetched from the CMS Coverage API or indexed in ChromaDB.

**Location:** `retrieval/` (all files)

**Impact:**
- The Coverage Validation Agent cannot be implemented without a retrieval pipeline.
- The "no citation → no finding" rule for coverage findings cannot be enforced (or demonstrated) without retrieved text.
- Medical necessity findings — the primary differentiator from rule-based scrubbers — do not exist.
- `data/reference/` is empty of CMS data.

**Recommended Fix:**
1. Implement `retrieval/ingest.py` to fetch LCDs and NCDs via the CMS MCD API.
2. Implement `retrieval/chunking.py` with section-aware splitting (keep policy sections intact).
3. Implement `retrieval/vector_store.py` ChromaDB wrapper with `index()` and `query()`.
4. Write an ingestion script that populates `data/reference/coverage/` and builds the ChromaDB index at `retrieval/chroma_db/`.

**Planned Sprint:** Phase 4 — LCD/NCD Retrieval Pipeline

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

#### TD-08: `tests/test_orchestrator.py` Remains a Stub (Partially Resolved)

**Description:** `tests/test_rules.py` was a stub — now resolved with 35 MUE, NCCI, and code_validity tests (Sprint 6). `tests/test_orchestrator.py` is still a docstring-only stub.

**Location:** `tests/test_orchestrator.py`

**Impact:**
- The orchestrator (when implemented in Phase 7) will have no test coverage at launch.
- MUE, NCCI, code_validity now have test coverage. NPI still lacks test coverage (pending Phase B).

**Recommended Fix:**
- `test_orchestrator.py`: implement tests with mocked LLM responses once the orchestrator is wired. Mock at the Anthropic SDK boundary, not at the Finding level.
- Add NPI rule tests to `test_rules.py` when `rules/npi.py` is implemented (Phase B).

**Planned Sprint:** Phase 7 (`test_orchestrator.py`); Phase B (`test_rules.py` NPI additions)

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

#### TD-12: No `.env` Guard or `ANTHROPIC_API_KEY` Check at Startup

**Description:** The app starts without checking whether `ANTHROPIC_API_KEY` is set. When the agent layer is wired, missing the API key will produce a confusing error deep in the Anthropic SDK rather than a clear startup message.

**Location:** `app/main.py` (top-level startup)

**Impact:**
- Currently low risk (agents not wired).
- Will produce a runtime error mid-demo the moment any agent is called without the key set.

**Recommended Fix:**
```python
import os
from dotenv import load_dotenv
load_dotenv()
if not os.getenv("ANTHROPIC_API_KEY"):
    st.error("ANTHROPIC_API_KEY not set. Add it to .env before running agents.")
    st.stop()
```
Add this check gated on whether agents are enabled, so it does not block the current demo.

**Planned Sprint:** Phase 5 (before wiring the first agent)

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

## Debt Summary

| Priority | Count | Resolved | Open |
|---|---|---|---|
| High | 11 | 9 (R1–R5, TD-01, TD-02, TD-03, TD-08 partial) | 3 (TD-04, TD-05, TD-06) |
| Medium | 7 | 3 (TD-07, TD-07b, TD-08 remainder partial) | 4 (TD-07a, TD-09, TD-10, TD-11, TD-12) |
| Low | 5 | 1 (TD-17) | 4 (TD-13, TD-14, TD-15, TD-16) |
| Sprint 3 additions | 3 | 3 | 0 |
| **Total** | **26** | **16** | **11** |

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
