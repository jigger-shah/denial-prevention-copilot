# Technical Debt Register
## Denial Prevention Copilot

**Last updated:** June 2026  
**Scope:** All known technical debt as of Sprint 3 (policy intelligence foundation)

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

---

## Open Debt

### HIGH Priority

---

#### TD-01: Only One Hardcoded NCCI PTP Edit Pair

**Description:** `rules/ncci.py` loads a single edit pair (`80053` / `80048`) from an in-memory list. The real CMS NCCI PTP table contains ~250,000+ edit pairs covering virtually every CPT code combination.

**Location:** `rules/ncci.py:_load_ptp_edits()`

**Impact:**
- The NCCI check is essentially non-functional for any claim that does not happen to bill both 80053 and 80048.
- Every demo claim other than CLM-001 and CLM-003 produces zero NCCI findings, regardless of what codes are billed.
- Claiming "NCCI validation" in a demo while running one hardcoded pair is misleading if the audience looks closely.

**Recommended Fix:**
1. Download the current CMS NCCI PTP file (free, quarterly, CSV) to `data/reference/ncci_ptp_<quarter>.csv`.
2. Implement `_load_ptp_edits()` to read and cache the CSV with columns: `col1`, `col2`, `modifier_indicator`, `effective_date`.
3. Derive `doc_id` from the filename (e.g., `"NCCI-PTP-2026Q2"`) and `edition` from the quarter.
4. Add a gitignore entry for `data/reference/*.csv` (already present).

**Planned Sprint:** Phase 3 — Complete Deterministic Layer

---

#### TD-02: `rules/mue.py` Is a Docstring-Only Stub

**Description:** The MUE (Medically Unlikely Edit) module exists as a stub with no implementation. MUE limits define the maximum units of service payable per HCPCS/CPT code per date of service. Exceeding the MUE for a code is a hard denial trigger (MAI=1) or a documentation-required denial (MAI=2/3).

**Location:** `rules/mue.py` (entire file)

**Impact:**
- Unit-of-service denial risks are completely undetected.
- MUE violations are among the most common denial reasons for labs, surgical codes, and durable medical equipment.
- The PRD explicitly lists MUE limits as a P0 deterministic validation requirement (§6 P0).

**Recommended Fix:**
1. Download the CMS NCCI MUE file to `data/reference/ncci_mue_<quarter>.csv`.
2. Implement `check_mue_limits(claim: ClaimIn) -> list[Finding]` that compares `claim.units[code]` against the MUE limit for each code.
3. Apply MAI-aware severity: MAI=1 → HIGH (hard denial), MAI=2/3 → MEDIUM (documentation may bypass).
4. Build `Citation` from the MUE file edition and MAI column.
5. Wire into `rule_engine.review_claim()`.

**Planned Sprint:** Phase 3 — Complete Deterministic Layer

---

#### TD-03: `rules/npi.py` Is a Docstring-Only Stub

**Description:** NPI validation is not implemented. A deactivated, invalid, or mismatched NPI is a hard denial trigger at all payers — Medicare will not process a claim with a deactivated NPI.

**Location:** `rules/npi.py` (entire file)

**Impact:**
- Claims with invalid NPIs pass through the rule layer with no finding.
- The NPI in `sample_claims.json` (`1234567890`, `9876543210`) are synthetic and may not pass even basic Luhn validation.
- The orchestrator's intended short-circuit behavior (hard NPI failure skips agent pass) cannot be demonstrated.
- PRD §6 P0 lists NPI lookup as a deterministic validation requirement.

**Recommended Fix:**
1. Implement Luhn algorithm check for 10-digit NPI format.
2. Implement `query_nppes(npi: str)` using the public NPPES REST API (`https://npiregistry.cms.hhs.gov/api/`).
3. Return HIGH finding if NPI is deactivated or not found; return MEDIUM if taxonomy does not match place of service.
4. Handle API timeout gracefully: return a LOW finding noting that NPI status could not be verified, rather than crashing.
5. Wire into `rule_engine.review_claim()` as the first check (before NCCI and MUE).

**Planned Sprint:** Phase 3 — Complete Deterministic Layer

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

#### TD-07: No Manual Claim Intake Form

**Description:** The UI reads claims exclusively from `data/synthetic/sample_claims.json`. There is no way for a user to enter a claim manually or upload a CSV of claims.

**Location:** `app/main.py` (claim selector section); `app/components/claim_form.py` (stub)

**Impact:**
- The demo is limited to 5 fixed claims. Cannot demonstrate the product with an arbitrary claim.
- Cannot show batch review mode (PRD §6 P1: "Batch review of an uploaded claim file").
- A live demo audience will notice the claim is pre-selected and not entered by the reviewer.

**Recommended Fix:**
1. Implement `app/components/claim_form.py` with text inputs for payer, NPI, CPT (multi-value), ICD-10 (multi-value), modifiers, POS, units.
2. Add a tab or mode switch: "Use sample claim" vs "Enter claim manually."
3. Phase 3 extension: CSV upload with column header validation.

**Planned Sprint:** Phase 3 — Complete Deterministic Layer (manual entry); Phase 3 extension (CSV batch)

---

#### TD-08: `tests/test_rules.py` and `tests/test_orchestrator.py` Are Stubs

**Description:** Two test files exist as docstring-only stubs describing the tests that should be written but have no test functions.

**Location:** `tests/test_rules.py`, `tests/test_orchestrator.py`

**Impact:**
- MUE, NPI, and reference-data code_validity have no test coverage.
- The orchestrator (when implemented) will have no test coverage at launch.
- `pytest` reports 35 collected tests; the stub files contribute 0.

**Recommended Fix:**
- `test_rules.py`: implement tests for MUE (MAI=1 → HIGH finding, MAI=2 → MEDIUM), NPI (valid/deactivated/invalid format), and code validity with reference file fixtures.
- `test_orchestrator.py`: implement tests with mocked LLM responses once the orchestrator is wired. Mock at the Anthropic SDK boundary, not at the Finding level.

**Planned Sprint:** Phase 3 (`test_rules.py`); Phase 7 (`test_orchestrator.py`)

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

#### TD-15: Citation Edition Is `"synthetic sample"` Throughout

**Description:** Every `Citation.edition` field is set to `"synthetic sample"`. In production, this should be the quarter string (NCCI) or fiscal year (ICD-10-CM) of the reference file consulted.

**Location:** `rules/ncci.py`, `rules/code_validity.py`

**Impact:**
- Audit log shows `"synthetic sample"` for every edition — not traceable to a real policy snapshot.
- A compliance reviewer looking at an export cannot verify which version of the NCCI was consulted.
- Low impact for demo; meaningful for governance claims.

**Recommended Fix:** When real CMS CSV files are loaded, derive the edition from the filename or file header and pass it through to the `Citation` object. This is already the design intent — the field exists for this purpose.

**Planned Sprint:** Phase 3 (when real reference files are loaded)

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

#### TD-17: Synthetic NPIs Do Not Pass Luhn Validation

**Description:** The sample claims use `1234567890` and `9876543210` as NPIs. These are not valid under the Luhn check digit algorithm used by CMS.

**Location:** `data/synthetic/sample_claims.json`

**Impact:**
- When `rules/npi.py` is implemented with Luhn validation, these claims will immediately produce an NPI finding.
- This may be the *intended* behavior for some test claims (CLM-001 might intentionally demonstrate an NPI issue), but it should be explicit.

**Recommended Fix:** Either generate valid synthetic NPIs (compute the correct Luhn check digit for a synthetic base number) or document which test claims are expected to fail NPI validation. Add a note in `data/synthetic/README.md`.

**Planned Sprint:** Phase 3 (when NPI validation is implemented)

---

## Debt Summary

| Priority | Count | Resolved | Open |
|---|---|---|---|
| High | 11 | 5 | 6 |
| Medium | 6 | 0 | 6 |
| Low | 5 | 0 | 5 |
| Sprint 3 additions | 3 | 3 | 0 |
| **Total** | **25** | **8** | **17** |

Items R1–R5 were addressed in the pre-audit model refactor and Sprint 2.  
Items R6–R8 were addressed in Sprint 3 (policy intelligence foundation).  
The 6 open High items (TD-01 through TD-06) represent the core gap between current state and a complete MVP.

**Sprint 3 note:** Local policy intelligence was introduced using curated public-policy-style references (`data/reference/policy_examples.json`). This makes the citation detail view evidence-backed without requiring CMS API automation, Chroma, or LLM calls. Real CMS/NCCI/LCD/NCD ingestion remains a future replacement point — `retrieval/policy_repository.py` is designed with the same public interface the ChromaDB-backed version will implement.
