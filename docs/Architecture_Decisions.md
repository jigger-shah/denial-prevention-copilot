# Architecture Decisions
## Denial Prevention Copilot

This document records the major architecture decisions made during development, the reasoning behind each, the alternatives considered, and the implications for future phases. Where decisions had lasting structural consequences, the ADR (Architecture Decision Record) format is used.

---

## ADR-001: Deterministic Rule Layer Before LLM Agents

**Status:** Decided — implemented  
**Decided:** Sprint 1

### Context

The system needs to check claim coding correctness (NCCI bundling, code validity, MUE limits, NPI status) and also reason about medical necessity against coverage policy (LCD/NCD). These are fundamentally different types of work. NCCI bundling is a binary lookup against a published edit table. Medical necessity for a specific diagnosis-procedure pair under a specific LCD requires reasoning over unstructured policy text.

### Decision

All deterministic lookups (NCCI PTP pairs, MUE limits, code validity, NPI status) run as a synchronous rule layer before any LLM call is made. The LLM is invoked only for tasks that cannot be answered by a lookup: coverage interpretation, documentation analysis, and synthesis.

### Rationale

**Accuracy:** Deterministic lookups against authoritative tables are 100% accurate for questions that have binary answers. An LLM reasoning about whether 80048 is bundled into 80053 will sometimes be right and sometimes wrong, and will never be as reliable as the edit table itself.

**Cost:** LLM calls cost money and add latency. Routing rule-answerable questions to the rule layer keeps costs low and response time fast.

**Explainability:** A rule finding citing "NCCI PTP edit table, Q2 2026, Column 1/Column 2, modifier indicator 0" is more credible and auditable than "the model says these two codes are bundled."

**Short-circuit on hard failure:** An invalid NPI (deactivated or non-existent) is a hard denial trigger that makes further review pointless. Running the rule layer first allows the orchestrator to return immediately with the NPI finding rather than spending LLM tokens on a claim that will be rejected regardless.

**PRD alignment:** PRD §5 Principle 3 states explicitly: "Deterministic before generative."

### Alternatives Considered

- **LLM-first:** Let the LLM handle NCCI checking. Rejected: less accurate, more expensive, less explainable, introduces variability where the answer is fixed.
- **Mixed (rules and LLM in parallel):** Run both simultaneously. Rejected: wastes LLM tokens when the rule check hard-fails; harder to reason about which layer produced which finding.

### Implications

- The rule layer runs synchronously and must complete before agents are dispatched.
- Rule modules (`rules/*.py`) must never import from `agents/` or call any LLM.
- Adding a new check: first ask "is this a lookup?" If yes, it belongs in `rules/`. If it requires reasoning over unstructured text, it belongs in `agents/`.

---

## ADR-002: Citation as a First-Class Data Model Before Persistence

**Status:** Decided — implemented  
**Decided:** Pre-audit refactor (between Sprint 1 and Sprint 2)

### Context

Sprint 1 represented `Finding.citation` as a plain `str` (e.g., "NCCI PTP — Q3 2025"). Before implementing the audit log, the planned schema for `audit_decisions` required three separate citation columns: `citation_doc_id`, `citation_section`, `citation_edition`. The flat string could not map to these columns without lossy parsing.

Additionally, the PRD requires that citations show the source excerpt inline in the UI, and that findings without a verifiable citation be suppressed. A string cannot carry an excerpt or be validated structurally.

### Decision

Introduce `Citation` as a first-class dataclass with one field per intended database column plus optional fields for inline display:

```python
@dataclass
class Citation:
    source: str           # human label: "NCCI PTP", "ICD-10-CM"
    doc_id: str           # stable document identifier for DB storage
    section: str          # table, chapter, or policy section
    edition: str          # version: quarter, FY, or "synthetic sample"
    effective_date: Optional[str] = None
    excerpt: Optional[str] = None
```

### Rationale

**Schema fidelity:** Each `Citation` field maps directly to one column in `audit_decisions`. No parsing, no inference, no lossy transformation at write time.

**Traceability:** When `citation.doc_id = "NCCI-PTP-2026Q1"` and `citation.edition = "2026Q1"`, the audit log reader can identify exactly which edition of which document was consulted for any historical finding.

**Citation integrity:** The "no citation → no finding" rule (PRD §5 Principle 2) requires the system to distinguish between "citation present" and "citation absent." A structured type makes this check unambiguous; a string does not.

**Excerpt support:** The UI expandable "View source excerpt" feature requires `citation.excerpt` to be a separate field. Embedding it in a display string would require parsing it back out.

**Permanent audit record:** The `audit_decisions` table is append-only. A schema migration on an append-only table leaves rows with the old shape alongside rows with the new shape. Getting the schema right before writing the first row is significantly cheaper than retrofitting.

### Alternatives Considered

- **Keep flat string, add columns at DB layer:** Parse the string into components at write time. Rejected: fragile (string format is not machine-stable), lossy (some information is lost in any round-trip), and produces a DB schema that cannot be trusted for audit purposes.
- **JSON blob column for citation:** Store the citation as a JSON string in one column. Rejected: makes the audit trail not queryable by column (cannot `WHERE citation_doc_id = 'X'`).

### Implications

- All rule modules construct a `Citation` object, not a string.
- When real CMS data files are loaded, `doc_id` becomes the versioned filename, and `effective_date` is read from the file header — the field is already present.
- The coverage validation agent's retrieved chunks must produce a `Citation` before any finding is emitted.

---

## ADR-003: SHA-256 Deterministic Finding Identity

**Status:** Decided — implemented  
**Decided:** Pre-audit refactor

### Context

The audit log's `audit_decisions` table records a human's decision on a specific finding. Without a stable identifier for findings, the decision row has no reliable foreign key. The naive approach — using list position (`findings[2]`) — fails as soon as findings are reordered, filtered, or supplemented by an agent layer.

### Decision

Every finding receives a `finding_id` computed as `SHA-256(claim_id:rule:issue)[:12]` — a 12-character lowercase hex string, stamped by the rule engine after sorting, before being returned to the UI.

```python
def _make_finding_id(claim_id: str, rule: str, issue: str) -> str:
    key = f"{claim_id}:{rule}:{issue}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]
```

### Rationale

**Stability across processes:** Python's built-in `hash()` is randomized per process (PYTHONHASHSEED). SHA-256 produces the same value in every process, on every machine, for every Python version.

**Stability across reruns:** The same claim, same rule, same issue always produces the same `finding_id`. If a claim is reviewed twice (e.g., after a correction), the decision row for the NCCI finding points to the same finding in both runs.

**Stability across display order changes:** Adding a new agent finding does not renumber existing findings. A decision on `finding_id = "9e76b012c9bf"` remains valid regardless of where that finding appears in a sorted list.

**No collisions in practice:** The 12-hex-char space (4.4 × 10^14) is far larger than the number of distinct findings any single claim can produce.

### Alternatives Considered

- **UUID:** Non-deterministic — a new UUID is generated each run, making it impossible to correlate decisions across reruns of the same claim.
- **Sequential integer:** Position-based — fails when findings are reordered.
- **Full SHA-256 (64 chars):** Correct but unnecessarily long for a human-readable audit log. 12 characters provide adequate collision resistance for this domain.

### Implications

- `finding_id` is computed by `rule_engine.py`, not by rule modules (rule modules do not have access to `claim_id`).
- All session state keys in the Streamlit UI are keyed by `finding_id` (e.g., `decision_{fid}`), not by position.
- The DB schema can use `finding_id` as a natural key for correlation even without a formal findings table.

---

## ADR-004: Governance and Audit Logging Before LLM Integration

**Status:** Decided — implemented  
**Decided:** Sprint 2

### Context

The PRD (§5 Principle 5, §12) requires governance by design: "Audit trail, confidence thresholds, and escalation paths are MVP scope, not a later phase. Trust is a launch requirement." The question is whether to build governance before or after wiring the LLM agents.

### Decision

Implement the complete human decision workflow (accept/override, override requires reason, named reviewer, Save Decision, Audit Trail view) and the audit persistence layer before writing a single LLM call.

### Rationale

**Governance retrofitting is expensive:** Adding an audit requirement after an AI system is in production means every path that produces findings must be updated to also log them. Building governance first means every future agent output automatically flows through the same persistence path from day one.

**Trust is established by the architecture, not the AI:** A compliance lead reviewing this system cares about whether the audit trail is complete and immutable. That property must hold for rule findings, agent findings, and all future findings equally. Establishing it before the first AI finding ensures no gap in the audit record.

**Demo sequencing:** Being able to show the audit trail before the AI is wired means the governance story can be demonstrated independently of AI quality. Interviewers can evaluate the governance design on its own terms.

**Forces the right data contract:** Implementing `AuditDecision` and `AuditRepository.save_decision()` before agents forces the agent layer to produce `Finding` objects that are already audit-ready. Without this forcing function, agents might return richer or looser structures that require transformation before persistence.

**PRD alignment:** PRD §12 lists governance controls as MVP requirements, not V2 nice-to-haves.

### Alternatives Considered

- **Governance later:** Build agents first, add audit logging when approaching launch. Rejected: this is the standard path that produces governance debt. Every team that has done it regrets it.
- **Lightweight audit (just log to a file):** Append JSON lines to a log file instead of SQLite. Rejected: not queryable, not filterable, not exportable to CSV per claim, not suitable for the compliance lead persona.

### Implications

- `AuditRepository.save_decision()` is the *only* path to persisting a decision. The UI never calls sqlite3 directly.
- The `audit_decisions` table uses INSERT only. If the schema must change, a new column with a default (or a new table) is added — never UPDATE, never DELETE.
- All future agents must produce `Finding` objects conforming to the existing schema. The schema is the contract.

---

## ADR-005: SQLite for Audit Persistence

**Status:** Decided — implemented  
**Decided:** Sprint 2

### Context

The audit log needs to be persistent, queryable by `claim_id` and `reviewer_name`, and exportable to CSV. Options include SQLite, a cloud database, a flat JSON file, or a time-series database.

### Decision

Use SQLite (`db/audit.db`) via the standard library `sqlite3` module with no ORM.

### Rationale

**Zero infrastructure:** SQLite requires no server, no configuration, no credentials. The file is created on first use by `initialize_database()`.

**Portfolio project appropriateness:** A production system would use PostgreSQL or a managed cloud database. For a portfolio demonstrating concepts, SQLite keeps the focus on the architecture rather than on database administration.

**Sufficient for the demo workload:** The audit log stores one row per human decision. Even reviewing 1,000 claims/day for a year produces ~500,000 rows — trivially within SQLite's performance envelope.

**Standard library only:** `sqlite3` is in Python's standard library. No dependency, no version mismatch, no install step.

**Portability:** The `.db` file can be copied, opened in any SQLite browser, and shared for review without standing up any infrastructure.

### Alternatives Considered

- **PostgreSQL:** Correct for production. Requires a running server, adds infrastructure complexity inappropriate for a portfolio project.
- **Pandas + CSV:** Queryable with pandas, but not append-only, not transactional, and not suitable as an audit log.
- **SQLAlchemy ORM:** Adds an abstraction layer. Rejected for simplicity: the schema is one table with 18 fixed columns. No ORM is needed.

### Implications

- `db/audit.db` is gitignored (`db/*.db` in `.gitignore`).
- The `DB_PATH` defaults to `pathlib.Path(__file__).parent / "audit.db"` — co-located with the repository code for development. Production would set this via environment variable.
- Tests use `tmp_path / "test_audit.db"` — the production database is never touched by the test suite.

---

## ADR-006: Repository Pattern for Database Access

**Status:** Decided — implemented  
**Decided:** Sprint 2

### Context

The Streamlit UI needs to save decisions to SQLite. The naive approach is to call `sqlite3.connect()` directly in `app/main.py`. The alternative is to introduce an abstraction layer.

### Decision

All database access goes through `AuditRepository` in `db/audit_repository.py`. The UI imports `AuditRepository` and calls its methods. The UI never imports `sqlite3`.

```python
# Correct
repo = get_repo()
repo.save_decision(audit_decision)

# Forbidden
conn = sqlite3.connect("db/audit.db")  # never in app/
```

### Rationale

**Testability:** `AuditRepository` accepts a `db_path` parameter. Tests pass a `tmp_path` fixture path and get a fresh isolated database. Without the repository pattern, testing UI code would require patching `sqlite3.connect` or writing to the production database.

**Governance enforcement:** `save_decision()` is the one place where governance rules are enforced (finding_id present, citation complete, override requires reason). With direct sqlite3 access, any caller could bypass these checks. With the repository, there is only one path to the database, and that path always validates.

**Replaceability:** If SQLite is replaced with PostgreSQL in production, the change is contained to `audit_repository.py`. The UI, tests, and any other callers see no change.

**PRD alignment:** PRD §11 implies that the audit log should be exportable per claim and queryable — requirements that belong in an abstraction, not scattered across UI code.

### Implications

- `get_repo()` is decorated with `@st.cache_resource` so the `AuditRepository` is initialized once per Streamlit session.
- Any future component (e.g., `app/components/audit_view.py`) that needs to read or write decisions must use `AuditRepository`, not raw SQL.

---

## ADR-007: Streamlit Widget Key Split for Session State Persistence

**Status:** Decided — implemented  
**Decided:** Sprint 2 bug fix

### Context

The override reason text area used the same key (`f"reason_{fid}"`) as both its Streamlit widget key and the slot read by `_save_controls`. When the user confirmed an override, `st.rerun()` was called. On the next render, the `override_pending` branch was skipped, so the text area was no longer rendered. Streamlit's widget cleanup removed the key from `session_state`, causing `save_decision()` to receive an empty `override_reason` and raise a `ValueError`.

### Decision

Split into two distinct keys:

- `f"reason_input_{fid}"` — the text area's widget key (Streamlit-owned, may be cleared on widget removal)
- `f"reason_{fid}"` — a plain `session_state` slot (application-owned, never used as a widget key, not subject to widget cleanup)

Before calling `st.rerun()` on Confirm, the reason is explicitly written to the application-owned slot:

```python
st.session_state[reason_key] = reason.strip()  # reason_key = f"reason_{fid}"
st.session_state[decision_key] = "overridden"
st.rerun()
```

### Rationale

Streamlit's widget state cleanup removes a key from `session_state` when the widget that owns that key is no longer rendered in a given script run. A key set directly via `st.session_state[key] = value` (not through a widget) is never subject to this cleanup, because Streamlit does not know it was once associated with a widget.

### Implications

- `_clear_review_state()` clears keys starting with `"reason_input_"` in addition to `"reason_"` and `"decision_"` and `"saved_"`.
- Any future widget that needs to persist state across a render where the widget disappears must follow this pattern: widget key ≠ storage key.

---

## ADR-008: Narrow AuditRepository Scope (One Table)

**Status:** Decided — implemented  
**Decided:** Sprint 2

### Context

The original `db/audit.py` stub defined a four-table design: `claims`, `findings`, `decisions`, `audit_events`, with separate write functions for each. The Sprint 2 task was to add persistence before the agent layer existed.

### Decision

Implement `AuditRepository` covering only the `audit_decisions` table. Defer the `claims`, `findings`, and `audit_events` tables to the sprint where agents are wired.

### Rationale

The `claims` and `findings` tables require the orchestrator and agents to populate them meaningfully. Without agents, these tables would be empty except for data redundant with `audit_decisions`. Building them now would create dead schema that the existing code cannot fill.

The `audit_decisions` table, by contrast, is actively populated by the human decision workflow built in Sprint 2. It is the only table that has a complete producer (the Streamlit UI) and a complete consumer (the Audit Trail view and CSV export).

Building only what is actively used avoids schema debt: unused tables suggest unimplemented features to anyone reading the code.

### Implications

- `db/audit.py` (the original stub with the four-table API) is now superseded but still present. It should be removed or formally replaced in Phase 3.
- When the orchestrator is implemented, it will need to write to `claims` and `findings` tables. At that point, the repository pattern means adding methods to `AuditRepository` (or a new `ClaimRepository`) rather than scattering SQL across the codebase.

---

## ADR-010: Manual Claim Intake Separated from Rendering

**Status:** Decided — implemented  
**Decided:** Sprint 4

### Context

Sprint 4 added Manual Claim Entry mode: a claim header form plus a dynamic service-line coding grid. The natural Streamlit pattern is to write transformation logic (normalization, deduplication, payer mapping) inline inside the function that renders the widgets. This makes the logic untestable without a running Streamlit app.

### Decision

All transformation and validation logic lives in `app/claim_intake.py` with no Streamlit imports. The UI (`app/main.py`) handles rendering only: it reads widget values from session state, calls `build_manual_claim()`, and passes the result to `load_claim()`. Session state management and on_change callbacks also live in `main.py`.

```
app/claim_intake.py          — pure Python, unit-testable
  PAYER_ID_MAP               — lookup table
  build_manual_claim()       — service-line grid → claim dict for load_claim()
  get_payer_id()             — name → payer ID
  validate_npi()             — format check (10 digits)
  normalize_code()           — strip + uppercase

app/main.py                  — Streamlit only
  _render_manual_mode()      — reads session state, calls claim_intake, renders UI
  _on_payer_name_change()    — on_change callback for payer selectbox
  _clear_manual_form()       — clears manual_ and sl_ session state keys
  _load_worked_example()     — loads WORKED_EXAMPLE into session state
```

### Rationale

**Testability:** `tests/test_claim_intake.py` runs 28 tests against `claim_intake.py` functions with no Streamlit, no session state, no running process. Inline logic cannot be tested this way.

**CLAUDE.md alignment:** The architecture constraint "Orchestrator is a Python controller, not an agent loop" implies business logic should not be buried in rendering code — the same principle applies to the UI layer.

**Single entry point into the rule engine:** `build_manual_claim()` is the only place that converts service-line grid data into the flat `cpt_codes`, `icd10_codes`, `modifiers` arrays that `load_claim()` and the rule engine expect. One place to audit, one place to fix.

**Backward compatibility:** `load_claim()` was updated to accept both `"payer"` (existing sample claims) and `"payer_name"` (manual claims) keys, with `npi` and `place_of_service` defaulting to `""` when absent. All 55 pre-Sprint 4 tests continue to pass unchanged.

### Alternatives Considered

- **Inline in render function:** Fast to write, impossible to test, conflates UI state with business logic.
- **Separate component in `app/components/claim_form.py`:** The stub exists but adding a Streamlit-coupled component there would still require a running app to test. The key split is between the transformation layer (no Streamlit) and the rendering layer (Streamlit).

### Implications

- Any future claim intake path (CSV upload, EHR integration) should call `build_manual_claim()` or a similar pure-Python builder, then pass the result to `load_claim()`. The rule engine never changes.
- `app/claim_intake.py` tests run in the deterministic test suite (`pytest tests/`) with no external dependencies, same as `test_rule_engine.py` and `test_audit.py`.
- `app/components/claim_form.py` stub remains; it could become the Streamlit rendering wrapper for the manual form if the component pattern is adopted in a future sprint.

---

## Deferred Architecture Decisions

### DEFER-001: RuleProvider Interface

**Decision pending:** Whether to introduce a `RuleProvider` protocol/ABC that all rule modules implement, allowing `rule_engine.py` to iterate over registered providers rather than calling each module explicitly.

**Current state:** `rule_engine.py` has two explicit calls: `ncci.check_ncci_pairs(claim)` and `code_validity.check_code_validity(claim)`.

**Trigger:** Introduce when adding a third rule module (MUE or NPI). The pattern becomes obvious at three callers; it is premature at two.

**Anticipated shape:**
```python
class RuleProvider(Protocol):
    def check(self, claim: ClaimIn) -> list[Finding]: ...

_PROVIDERS: list[RuleProvider] = [ncci, code_validity, mue, npi]
```

---

### DEFER-002: RiskScorer Abstraction

**Decision pending:** Whether to extract claim-level risk aggregation from `overall_risk()` in `rule_engine.py` into a `RiskScorer` class that can apply payer-specific heuristics and historical denial pattern weights.

**Current state:** `overall_risk()` is four lines: return the highest severity present.

**Trigger:** Introduce when the Denial Prevention Agent is implemented and needs to apply CARC pattern heuristics or payer-specific risk adjustments to the severity ranking.

---

### DEFER-003: RiskAssessment Pydantic Model

**Decision pending:** Whether `RiskAssessment` (referenced in CLAUDE.md as the orchestrator's return type) should be a Pydantic model or a plain dataclass.

**Current state:** Not yet implemented. `agents/denial_prevention.py` is a stub.

**Recommendation when implemented:** Use Pydantic for `RiskAssessment` because it is a cross-boundary object (agent layer → UI) and benefits from validation. Keep `Finding` and `Citation` as plain dataclasses (no external dependency in the rule layer).

---

### DEFER-004: Multi-Table Audit Schema

**Decision pending:** Schema for `claims`, `findings`, and `audit_events` tables.

**Current state:** Described in `db/audit.py` stub (docstring only). `db/schema.py` has the column reference for `audit_decisions` only.

**Trigger:** Introduce when the orchestrator is implemented and begins writing claim review sessions to the database.

---

### DEFER-005: Embedding Provider Selection

**Decision pending:** Whether to use ChromaDB's default embedding function (all-MiniLM-L6-v2) or an Anthropic/OpenAI embedding model for the vector store.

**Current state:** `retrieval/vector_store.py` stub notes: "defaults to chromadb's built-in embedding function... Can be swapped via environment variable EMBEDDING_PROVIDER."

**Trigger:** Implement when building the LCD/NCD retrieval pipeline (Phase 4). The choice affects retrieval quality and cost. Default to the built-in model for the portfolio; document the swap path.

---

## Future Replacement Points

These are the points in the current implementation where production deployment would require a change.

| Component | Current (Portfolio) | Production Replacement |
|---|---|---|
| NCCI PTP data | 1 hardcoded edit pair | Quarterly CMS CSV loaded from `data/reference/` |
| MUE data | Stub | Quarterly CMS CSV |
| ICD-10-CM rules | 1 hardcoded dx rule | Annual FY reference file |
| Citation edition | `"synthetic sample"` | Actual quarter/year from CMS file header |
| NPI validation | Stub | Live NPPES REST API with Luhn validation |
| Claim source | JSON file selector | Manual intake form + CSV batch upload |
| Vector store | Stub | ChromaDB with real LCD/NCD chunks |
| LLM | Not wired | Claude Sonnet 4.6 via Anthropic SDK, structured tool use |
| Database | SQLite | PostgreSQL or managed cloud DB |
| Deployment | Local Streamlit | Streamlit Cloud or containerized deployment |
| PHI boundary | Not applicable (synthetic) | Customer-environment deployment with no data egress |

---

## ADR-009: Local Policy Reference Dataset Before CMS API Integration

**Status:** Decided — implemented  
**Decided:** Sprint 3

### Context

The app's citation detail view displays structured policy references (title, section, edition, effective_date, excerpt, source_url) for each finding. In Sprint 1–2, citation fields were populated inline in each rule module using synthetic placeholder strings. The Citation dataclass existed, but the data behind it was not traceable to any real reference source, making the citation detail view feel hollow.

The full production path for policy references — fetching LCD/NCD documents from the CMS MCD API, section-aware chunking, and ChromaDB vector indexing — is a multi-sprint effort that depends on the agent layer, which is not yet built.

### Decision

Sprint 3 introduced a curated JSON dataset (`data/reference/policy_examples.json`) with 5 public-policy-style reference entries and a read-only repository service (`retrieval/policy_repository.py`) that provides structured lookups by document_id and by code set. Rule modules were updated to reference document IDs from this dataset. The Streamlit UI was updated to enrich citation cards with title, source URL, and notes pulled from the repository.

### Rationale

**Evidence-backed feel without premature complexity.** The app can now show a coherent "View policy detail" panel with real field values, CMS source URLs, and policy-level excerpts — without any LLM, vector store, or live API.

**Same interface, different backing.** `retrieval/policy_repository.py` exposes `load_policy_references()`, `find_policy_by_document_id()`, `find_policies_by_codes()`, and `get_citation_detail()`. When the RAG pipeline is built, `_load_policy_references()` is replaced with a ChromaDB query; the public interface stays the same.

**Citation integrity.** `doc_id` values in rule modules now reference entries in `policy_examples.json`. Tests verify that every finding's `citation.doc_id` resolves to a policy entry — meaning the connection between a rule finding and its policy source is verified at test time, not just assumed.

**Schema stability.** The `Citation` dataclass is unchanged. No new fields were added to `Finding`. The policy repository is an additive enrichment layer, not a schema change.

### Alternatives considered

| Option | Reason not chosen |
|---|---|
| Keep synthetic strings, add detail view later | Detail view without real content is meaningless at demo time; cost of deferring was higher than cost of the JSON dataset |
| Build ChromaDB pipeline now | Requires agent layer, LCD/NCD ingestion, and vector store infrastructure — all out of scope for Sprint 3 |
| Embed all policy metadata in rule module dicts | Creates a second source of truth when the real pipeline lands; harder to replace |

### Production replacement

Replace `_load_policy_references()` in `retrieval/policy_repository.py` with a ChromaDB query after `retrieval/ingest.py` and `retrieval/vector_store.py` are implemented. The public interface (`find_policy_by_document_id`, `find_policies_by_codes`, `get_citation_detail`) stays unchanged. The JSON file can be removed once the vector store is seeded.

---

## Tradeoffs Summary

| Decision | Speed | Correctness | Explainability | Future-Proofing |
|---|---|---|---|---|
| Rules before LLM | ✅ Fast rule pass | ✅ Binary accuracy for lookups | ✅ Cite the table | ✅ Clear extension points |
| Citation dataclass | ➖ More code per rule | ✅ Schema-safe | ✅ Queryable per field | ✅ Agent layer inherits it |
| SHA-256 finding_id | ➖ Tiny compute cost | ✅ Cross-process stable | ✅ Auditable identity | ✅ No migration needed |
| Governance before AI | ➖ Delayed AI demo | ✅ No governance debt | ✅ AI decisions are auditable from day one | ✅ Agents inherit the contract |
| SQLite | ✅ Zero infra | ➖ Not production-scale | ➖ Not distributed | ➖ Swap needed for scale |
| Repository pattern | ➖ More code | ✅ Testable, consistent | ✅ One validation path | ✅ DB swap is contained |
| Widget key split | ➖ Two keys to manage | ✅ State survives rerender | — | ✅ Pattern reusable |
| Narrow audit scope | ✅ Ships sooner | ➖ Incomplete schema | — | ✅ No dead tables |
| Local policy JSON | ✅ No infra required | ➖ Curated, not comprehensive | ✅ Real source URLs shown | ✅ Same interface as future ChromaDB |
| Intake transform separate from render | ➖ Two files instead of one | ✅ Logic testable without Streamlit | ✅ One entry point to audit | ✅ Rule engine unchanged for all intake paths |
