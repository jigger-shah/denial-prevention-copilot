# Pre-Audit Architecture Review
## Denial Prevention Copilot — Permanent Record

**Reviewed after:** Sprint 1 (`cf322d9` — Build deterministic claim review v0.1)  
**Reviewed before:** Sprint 2 (`ee45738` — Add audit logging, human decision workflow)  
**Author:** Jigger Shah  
**Purpose:** Permanent record of the architectural state before persistence was added, the gaps identified, the refactoring recommended and executed, and the rationale for every model change that preceded the audit log.

---

## 1. Architecture State at End of Sprint 1

### What existed

One working vertical slice: a deterministic rule layer behind a Streamlit UI.

```
app/main.py  (Streamlit)
    └── rules/rule_engine.py
            ├── rules/ncci.py          IMPLEMENTED: 1 hardcoded PTP edit pair
            └── rules/code_validity.py IMPLEMENTED: 2 hardcoded rule tables
```

Everything else — agents, retrieval, DB, app/components — was a docstring-only stub.

### Data flow (Sprint 1)

```
User selects claim → app/main.py
    → load_claim(dict) → ClaimIn
    → review_claim(ClaimIn) → list[Finding]
    → overall_risk(findings) → "HIGH" | "MEDIUM" | "LOW" | "CLEAN"
    → _finding_card(finding, index)  ← index = positional
    → st.session_state["decision_0"] = "accepted" | "overridden"
    (nothing persisted)
```

### What Sprint 1 did well

| Strength | Detail |
|---|---|
| Layer separation | `rules/` has no UI imports; `app/main.py` has no business logic |
| Input contract | `ClaimIn` dataclass shared by all rule modules |
| Pure scoring | `overall_risk()` is a pure function with no side effects |
| Test discipline | 12 tests, no network, no mocks, all inline data |
| Stub skeleton | All future modules existed as docstrings, making the intended architecture legible |

### What Sprint 1 left unresolved

| Gap | Why it blocks persistence |
|---|---|
| `Finding.citation` was a flat `str` | Could not map to the 3-column DB schema: `citation_doc_id`, `citation_section`, `citation_edition`. Parsing the string at write time would be fragile and lossy. |
| No finding identity field | No way to write a foreign key from a decision row to the specific finding it answered. Decisions referenced by list position only. |
| No `source` field | Could not distinguish rule-layer findings from future agent findings in a shared audit table. |
| Session state keys were positional | `decision_0`, `reason_0` etc. — if findings are reordered (e.g., agent adds a HIGH finding at the front), all keys silently shift. A saved decision would reference the wrong finding after any list change. |

---

## 2. Component Analysis

### Implemented modules (functional code at end of Sprint 1)

| Module | Status | What it does |
|---|---|---|
| `rules/models.py` | Partial | `ClaimIn` dataclass; `Finding` with `citation: str` (pre-refactor) |
| `rules/rule_engine.py` | Functional | `load_claim()`, `review_claim()`, `overall_risk()`; no finding_id |
| `rules/ncci.py` | Partial | 1 hardcoded PTP edit pair (80053/80048); returns `Finding` with flat citation string |
| `rules/code_validity.py` | Partial | 2 hardcoded rule tables; returns `Finding` with flat citation strings |
| `app/main.py` | Functional | Claim selector, color-coded finding cards, Accept/Override with positional session keys |
| `tests/test_rule_engine.py` | Functional | 12 tests covering NCCI bundling, dx conflict, modifier, risk level, ordering |

### Stub modules (docstring-only skeletons)

| Module | Stub describes |
|---|---|
| `rules/mue.py` | MUE table lookup with MAI-aware severity |
| `rules/npi.py` | Live NPPES NPI Registry API client with Luhn validation |
| `agents/orchestrator.py` | Parallel agent dispatch, confidence-based escalation |
| `agents/coding_validation.py` | NCCI + MUE + modifier rules backed by the rule layer |
| `agents/coverage_validation.py` | RAG over LCD/NCD → Claude API → cited medical necessity findings |
| `agents/documentation_review.py` | LLM analysis of clinical note for E/M support and specificity |
| `agents/denial_prevention.py` | Deterministic synthesis of all findings into RiskAssessment |
| `retrieval/ingest.py` | CMS Coverage API fetch and save |
| `retrieval/chunking.py` | Section-aware LCD/NCD document splitting |
| `retrieval/vector_store.py` | ChromaDB index and query interface |
| `db/schema.py` | DDL stubs and Pydantic model descriptions |
| `db/audit.py` | Four-table write API: write_claim, write_finding, write_decision, write_event |
| `app/components/claim_form.py` | Manual claim intake with CSV batch upload |
| `app/components/findings_panel.py` | Findings display with Accept/Modify/Override |
| `app/components/audit_view.py` | Decision trail display |
| `tests/test_rules.py` | Planned MUE, NPI, and reference-data tests |
| `tests/test_orchestrator.py` | Planned end-to-end tests with mocked LLM responses |

---

## 3. Hardcoded Assumptions

Every item below is a synthetic placeholder that must be replaced before any claim with real data can be reviewed.

### Rule data

| Assumption | Location | Value | Production replacement |
|---|---|---|---|
| NCCI PTP edit pair | `rules/ncci.py:_load_ptp_edits()` | One pair: 80053/80048, modifier indicator 0 | CMS quarterly PTP CSV (~250,000 edit pairs) |
| Dx-procedure conflict | `rules/code_validity.py:_load_dx_procedure_rules()` | Z00.00 conflicts with 99202–99215 | ICD-10-CM FY reference data (thousands of rules) |
| Missing modifier rule | `rules/code_validity.py:_load_modifier_rules()` | Missing modifier 25 in preventive context | NCCI Policy Manual quarterly update |
| Citation `doc_id` | All rule modules | `"NCCI-PTP-SYNTHETIC"`, `"ICD10CM-FY2026"`, `"NCCI-POLICY-MANUAL"` | Versioned filename from actual CMS file |
| Citation `edition` | All rule modules | `"synthetic sample"` | Quarter string (NCCI) or FY year (ICD-10-CM) |
| Citation `effective_date` | All rule modules | `None` | ISO-8601 date from CMS file header |

### Claims and identifiers

| Assumption | Location | Value | Notes |
|---|---|---|---|
| Sample NPIs | `data/synthetic/sample_claims.json` | `1234567890`, `9876543210` | Synthetic; may not pass Luhn check digit validation |
| Claim set | `data/synthetic/sample_claims.json` | 5 claims | Cover PRD worked example and 4 edge cases; no PHI |

### Confidence scores

| Rule | Hardcoded value | Rationale |
|---|---|---|
| `ncci_ptp` | 0.95 | Binary lookup; very high certainty |
| `dx_procedure_conflict` | 0.90 | Clear policy rule; one known exception |
| `missing_modifier_25` | 0.75 | Clinical context required; genuine ambiguity |

---

## 4. Technical Debt Identified

### High — blocked persistence or correctness

| ID | Debt | Location | Status |
|---|---|---|---|
| TD-R1 | `Finding.citation` was a flat `str` — could not map to 3-column DB schema | `rules/models.py` | ✅ **Resolved** in pre-audit refactor |
| TD-R2 | No stable finding identity | `rules/rule_engine.py` | ✅ **Resolved** — SHA-256 `finding_id` |
| TD-R3 | Session state keys positional (`decision_0`, `reason_0`) | `app/main.py` | ✅ **Resolved** — `finding_id`-keyed |
| TD-R4 | Widget key reused as persistent storage for override reason | `app/main.py` | ✅ **Resolved** in Sprint 2 bug fix |
| TD-R5 | No `source` field to distinguish rule vs. agent findings | `rules/models.py` | ✅ **Resolved** — `source: str = "rule_layer"` |

### High — open (blocks MVP completeness)

| ID | Debt | Location |
|---|---|---|
| TD-01 | 1 hardcoded NCCI PTP pair; no CSV loader | `rules/ncci.py` |
| TD-02 | `rules/mue.py` stub — MUE checks absent | `rules/mue.py` |
| TD-03 | `rules/npi.py` stub — NPI validation absent | `rules/npi.py` |
| TD-04 | All agents are stubs | `agents/` |
| TD-05 | RAG retrieval pipeline not built | `retrieval/` |
| TD-06 | 2 hardcoded coding rules; no reference files loaded | `rules/code_validity.py` |

See `docs/Technical_Debt_Register.md` for the complete register with priorities and remediation plans.

---

## 5. Recommended Abstractions

### Implemented in Sprint 2

**`AuditRepository` (db/audit_repository.py):** The pre-audit review recommended a repository pattern to isolate all DB access behind a single abstraction. This was implemented in Sprint 2. The UI never calls sqlite3 directly; all validation (citation required, finding_id required, override reason required) lives in `save_decision()`.

### Deferred — right time not yet reached

**`RuleProvider` interface:**  
Replace explicit calls in `rule_engine.py` with an iterable of registered provider objects:
```python
class RuleProvider(Protocol):
    def check(self, claim: ClaimIn) -> list[Finding]: ...
```
*Trigger:* Introduce when adding the third rule module (MUE or NPI). Premature with two callers.

**`RiskScorer` class:**  
Encapsulate claim-level risk aggregation so payer-specific heuristics can be applied:
```python
class RiskScorer:
    def score(self, findings: list[Finding]) -> RiskAssessment: ...
```
*Trigger:* Introduce when the Denial Prevention Agent is implemented and needs to apply CARC pattern weights.

**`RiskAssessment` Pydantic model:**  
The orchestrator's return type (referenced in CLAUDE.md) has not been implemented. When built, use Pydantic (for cross-boundary validation) rather than a plain dataclass.  
*Trigger:* Implement with the orchestrator (Phase 7).

**Multi-table audit schema:**  
The original `db/audit.py` stub described `claims`, `findings`, `decisions`, and `audit_events` tables. Only `audit_decisions` was implemented in Sprint 2 (the only table actively populated by Sprint 2 features).  
*Trigger:* Implement `claims` and `findings` tables when the orchestrator is wired and has something to write.

---

## 6. Justification for Introducing Citation, finding_id, and source Before Persistence

This section documents the reasoning behind the pre-audit model refactor as a permanent architectural record.

---

### 6.1 Citation Dataclass

**What changed:**  
`Finding.citation: str` → `Finding.citation: Citation` where `Citation` is a dataclass with `source`, `doc_id`, `section`, `edition`, `effective_date`, `excerpt`.

**The persistence mapping problem:**  
The planned `audit_decisions` schema has columns `citation_source`, `citation_doc_id`, `citation_section`, `citation_edition`. A flat string like `"NCCI PTP — Q3 2025"` cannot be split into these four columns reliably:
- No stable delimiter
- Some strings include effective dates, some do not
- The `excerpt` field has no place in the string at all

Writing a flat string to a single `citation_text` column would make the audit log unqueryable by citation source and untraceable to a specific document edition.

**The citation integrity problem:**  
The PRD requires that "findings without a verifiable citation are suppressed" (§5 Principle 2, §7 Story 2). Enforcing this requires the system to distinguish "citation present" from "citation absent" structurally. A string is always present (even if empty); a typed dataclass makes the distinction unambiguous.

**The excerpt problem:**  
The UI's "View source excerpt" feature requires `citation.excerpt` as a distinct field. Embedding it in a display string would require parsing it back out, which cannot be done reliably.

**Why Citation was added before the first INSERT:**  
The `audit_decisions` table is append-only. Schema migrations on append-only tables leave rows with the old shape alongside rows with the new shape — queries must handle both. Getting the structure right before the first row is written is far cheaper than retrofitting.

---

### 6.2 finding_id via SHA-256

**What changed:**  
`Finding.finding_id: str = ""` added. Stamped by `rule_engine._make_finding_id(claim_id, rule, issue)` using SHA-256.

**The foreign key problem:**  
The `audit_decisions` table stores human decisions on specific findings. Without a stable identifier, a decision row has no reliable way to reference which finding it answered. Possible alternatives and why they fail:

| Option | Failure mode |
|---|---|
| List position (`findings[2]`) | Fails if any upstream sort order changes; agents adding findings renumber everything |
| UUID | Non-deterministic — different UUID each run, correlation across reruns impossible |
| Sequential integer per session | Position-based, same failure as list index |
| SHA-256(claim_id, rule, issue) | ✅ Stable across processes, machines, runs, and list reorderings |

**Why the 12-character truncation:**  
Full SHA-256 (64 chars) is unnecessarily long for a human-readable audit log. The 12-hex-char truncation provides a space of 4.4 × 10^14 possible values — far larger than the number of distinct findings any claim can produce. Collision probability across the entire expected lifetime of the audit log is negligible.

**Why SHA-256 not Python's `hash()`:**  
Python's built-in `hash()` uses a randomized seed (PYTHONHASHSEED) that changes between interpreter restarts. The same value produces a different `hash()` result in a new process. SHA-256 is deterministic across all Python versions, operating systems, and processes.

**The session state implication:**  
Once `finding_id` exists, Streamlit session state keys can be `decision_{finding_id}` rather than `decision_{index}`. This means:
- A new HIGH finding from an agent inserted at position 0 does not shift `decision_1` to reference a different finding.
- The same key persists across re-runs of the same claim review.
- The `finding_id` in session state matches the `finding_id` in the audit log row — the UI and DB refer to the same object using the same identifier.

---

### 6.3 source Field

**What changed:**  
`Finding.source: str = "rule_layer"` added.

**The provenance problem:**  
The planned system has two distinct sources of findings: the deterministic rule layer and the AI agent layer. These findings will coexist in the same `audit_decisions` table and in the same findings panel. Without a `source` field:
- The audit trail cannot distinguish rule findings from AI findings.
- The evaluation pipeline cannot compute precision/recall per agent type.
- A compliance reviewer cannot answer "which of these decisions were based on AI output?"

**Why not derived from the `rule` field:**  
Rule names like `"ncci_ptp"`, `"dx_procedure_conflict"` are specific to individual rule types. Adding an agent with its own rule names (e.g., `"coverage_lcd"`, `"em_level_support"`) would require adding each to a lookup table to derive the source. A direct `source` field is simpler and more robust.

**Why `"rule_layer"` as the default:**  
All current findings come from the rule layer. Setting the default to `"rule_layer"` means existing tests and rule modules produce correct output without any change. Agent modules will set `source="coverage_validation"`, `source="documentation_review"`, etc. explicitly.

**Governance implication:**  
Starting from the first row in `audit_decisions`, every finding's source is recorded. There will be no gap in the audit history — even historical decisions from before agents were wired are correctly labeled as rule layer decisions.

---

## 7. What the Pre-Audit Refactor Changed (Summary Table)

Committed as `dc681f2 — Refactor finding model for audit readiness`.

| Dimension | Before (Sprint 1) | After (pre-audit refactor) |
|---|---|---|
| `Finding.citation` type | `str` — flat display string | `Citation` dataclass — 6 fields, maps field-for-field to DB columns |
| Finding identity | None — list position only | `finding_id: str` — 12-char SHA-256, stamped by rule engine after sort |
| Finding provenance | None | `source: str = "rule_layer"` — identifies producing subsystem |
| Session state keys | `decision_0`, `reason_0` — positional | `decision_{finding_id}`, `reason_{finding_id}` — content-based |
| UI citation display | `_citation_caption(citation: str)` | `_citation_caption(citation: Citation)` — structured field access |
| Source excerpt display | Not present | `st.expander("View source excerpt")` — reads `citation.excerpt` |
| Test count | 12 tests | 20 tests (+8 structure tests for finding_id, Citation, source) |
| Observable UI behavior | Unchanged | Unchanged — the refactor was purely a model upgrade |

---

## 8. Invariants Established by This Refactor

These are the properties the pre-audit refactor guarantees, which all future phases must maintain.

1. **Every `Finding` has a non-empty `finding_id` after `rule_engine.review_claim()` returns.** Rule modules return findings with empty `finding_id`; the engine stamps it after sorting. Nothing downstream should depend on `finding_id` being populated before `review_claim()` returns.

2. **`finding_id` is stable across runs.** `SHA-256(claim_id:rule:issue)[:12]` — if any of these three inputs change, the ID changes. They must not change for the same logical finding.

3. **`Citation` is a required field, not optional.** `Finding.citation: Citation` (no Optional). Every rule module must construct a Citation. The UI and persistence layer assume it is always present.

4. **`citation.source` and `citation.doc_id` must be non-empty.** `AuditRepository.save_decision()` enforces this: findings with an empty `citation_source` or `citation_doc_id` are rejected. This is the "no citation → no finding" rule at the persistence layer.

5. **`source` defaults to `"rule_layer"` for all current findings.** Agent modules override this. Any Finding that has not explicitly set `source` should be from the rule layer.

6. **Session state keys are keyed by `finding_id`, never by position.** New keys follow the `{prefix}_{finding_id}` pattern. `_clear_review_state()` clears by prefix, not by index range.
