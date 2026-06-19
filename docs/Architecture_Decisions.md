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

**Demo sequencing:** Being able to show the audit trail before the AI is wired means the governance story can be demonstrated independently of AI quality. Reviewers can evaluate the governance design on its own terms.

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

### ~~DEFER-003: RiskAssessment Pydantic Model~~ — Resolved Phase 7 (plain dataclass chosen)

**Resolution:** Implemented as a plain `dataclass` in `rules/models.py`, consistent with `Finding` and `Citation`, not Pydantic. `RiskAssessment(score, findings, escalation_required, checks_run)` is constructed entirely from already-validated `Finding` objects within a single process (`agents.orchestrator` → `agents.denial_prevention` → `app/main.py`) — it never crosses a serialization boundary (no JSON API, no DB round-trip) in the light-orchestrator scope, so Pydantic's validation-on-parse benefit doesn't apply. Revisit if `RiskAssessment` is ever persisted directly or exposed over an API.

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

## ADR-011: File-Backed NCCI PTP Lookup with Synthetic Fallback

**Status:** Decided — implemented
**Decided:** Sprint 5

### Context

Sprint 1 used a single hardcoded NCCI PTP edit pair (80053/80048). The real CMS NCCI Practitioner PTP table contains ~250,000+ active edit pairs. The system needs to validate any CPT code combination a user enters, not just the one worked example.

CMS publishes the NCCI PTP edits as quarterly Excel (.xlsx) files (four files per release, each ~600K rows). The files are free, available from the CMS NCCI download page, and are gitignored from the repository.

### Decision

Implement `rules/ncci_loader.py` that:
- Discovers all `.xlsx` files in `data/reference/ncci/` at runtime
- Loads active edit pairs (deletion_date == "*") into a cached Python dict keyed by (col1, col2) tuples
- Caches the result via `functools.lru_cache` — loaded once per Python process, O(1) per lookup
- Provides `lookup_ncci_pair(code_a, code_b)` that checks both code orderings (since CMS files are directional: col1 = comprehensive, col2 = component)

`rules/ncci.py` uses the loader and falls back to a single hardcoded synthetic pair when no CMS files are present, preserving demo behavior in portable environments.

### Rationale

**Complete coverage:** The real NCCI table covers ~1.73M active edit pairs (across 4 files). Any CPT code the user enters can be checked against the real CMS data.

**Portability by default:** The repo does not require CMS files to run. The synthetic fallback fires when `data/reference/ncci/` is empty, allowing the app to demo without the 4 large xlsx files.

**No database yet:** The in-memory dict (~84 MB shallow) is sufficient for the lookup volume of a portfolio demo. A future sprint could pre-build a SQLite index for faster startup.

**Update path is explicit:** `NCCI_VERSION` and `NCCI_EFFECTIVE_DATE` constants in `ncci_loader.py` are updated once per quarter. Replacing the xlsx files and restarting the app is sufficient.

### Performance characteristics

| Step | Time | Notes |
|---|---|---|
| First load (4 xlsx files, ~2.6M rows) | ~54 seconds | One-time per Python process |
| Subsequent lookups | O(1), < 1 ms | Dict keyed by (col1, col2) tuple |
| Memory (in-process) | ~84 MB shallow | 1.73M active pairs cached |

### Tradeoffs

- **First review is slow (54s):** Acceptable for a portfolio demo; documented. A future sprint could pre-serialize the dict to a pickle/parquet file for faster startup.
- **Whole-file load:** Pandas reads the entire xlsx, not row-by-row. This is necessary because CMS files have no sort guarantee on col1.
- **No duplicate resolution:** If the same (col1, col2) pair appears in multiple files, the first file wins.

### Alternatives Considered

- **SQLite index:** Faster startup after first build; requires a build step and additional infra. Deferred (DEFER-001 placeholder: "Phase 3 extension").
- **Keep hardcoded pair only:** Simple but misleads any audience who looks at the NCCI validation claim. Rejected.
- **Load per-request:** Reloads all 4 files on every claim review. Rejected: 54s per review is not acceptable.

### Implications

- `data/reference/ncci/*.xlsx` is gitignored. The README must document how to download the files.
- `ncci_loader._clear_ncci_cache()` must be called in tests that need to inject a different reference directory.
- When CMS releases a new quarterly edition, update `NCCI_VERSION` and `NCCI_EFFECTIVE_DATE` in `ncci_loader.py`, replace the xlsx files, and restart.

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

## ADR-012: Coverage Validation Agent v1 — JSON-Backed Retrieval, No ChromaDB

**Status:** Decided — implemented
**Decided:** Sprint 9

### Context

The Coverage Validation Agent (Phase 5 in the roadmap) requires a retrieval layer to ground LLM reasoning in policy documents. The full retrieval pipeline — `retrieval/ingest.py` (CMS Coverage API client), `retrieval/chunking.py` (section-aware splitting), `retrieval/vector_store.py` (ChromaDB interface) — is a 2–3 session effort with external dependencies (ChromaDB, ~90MB download) and requires live CMS API access for ingestion. These dependencies were out of scope for Sprint 9, whose goal was to ship the first live LLM call with proper governance.

### Decision

Coverage Validation Agent v1 uses the existing JSON-backed policy repository (`retrieval/policy_repository.py`) for retrieval. Three LCD-style entries were added to `data/reference/policy_examples.json` with diagnosis-driven `applies_to_codes` (ICD-10 codes, not CPT codes): `LCD_E_M_MEDICAL_NECESSITY_Z00`, `LCD_E_M_MEDICAL_NECESSITY_I10`, `LCD_PREVENTIVE_99395_COVERAGE`. The agent calls `find_policies_by_codes(cpt_codes, icd10_codes)` and filters to `source_type in {"LCD", "NCD"}` — no ChromaDB, no CMS API ingestion.

All other agent governance decisions are identical to what the ChromaDB version will use:
- One model call per invocation (`tool_choice={"type": "any"}`, max 3 policies)
- Two-tool schema: `report_coverage_finding` and `no_coverage_concern`
- Citation grounding: `citation_doc_id` must be in the retrieved set or the finding is suppressed
- No finding without an API key; no finding without matching LCD/NCD policy; no finding on model error

### Rationale

**Ship the governance contract now.** The most important design decisions in the coverage agent are not retrieval mechanics — they are the citation grounding rule, the tool-use schema, the error isolation, and the session state integration. These can all be built, tested, and validated against the JSON policy repository without ChromaDB. The ChromaDB upgrade changes only the retrieval call; all governance remains identical.

**Avoid heavyweight dependencies in Sprint 9.** ChromaDB installs as a ~90MB package and requires initialization before indexing can run. Requiring this for a sprint whose goal is to demonstrate the first LLM call creates unnecessary risk of setup friction at demo time.

**Diagnosis-driven applies_to_codes.** LCD entries use ICD-10 codes in `applies_to_codes` rather than CPT codes. This avoids false retrieval: if 99213/99214 were in `applies_to_codes`, the coverage agent would retrieve and analyze E/M coverage policies for every claim containing those codes — including claims where the E/M is not in question. Diagnosis-driven retrieval means coverage analysis is triggered by the diagnostic context (Z00.00 = well visit with possible medical necessity concern) rather than the procedure.

**One-call cost protection.** `tool_choice={"type": "any"}` guarantees the model calls exactly one tool, keeping the cost per button click to a single API call. Combined with the no-automatic-call requirement, this ensures the "Run AI Coverage Analysis" button is the only trigger point for LLM spend.

### Upgrade Path

Replace the `find_policies_by_codes(...)` call and `_LCD_SOURCE_TYPES` filter in `coverage_validation.py` with `retrieval.vector_store.query(text, n_results=_MAX_POLICIES)` after Phase 4 is complete. The `validate_coverage(claim)` signature, tool schema, citation grounding logic, and all tests are unaffected by this change. The JSON entries can be retained as regression fixtures.

### Alternatives Considered

- **Ship ChromaDB in Sprint 9:** Rejected — too heavy for a sprint focused on governance wiring. First LLM call should be simple enough to reason about completely.
- **Stub the retrieval call (always return the same 3 docs):** Rejected — this doesn't test the retrieval filter or the "no matching policy → no finding" governance path.
- **Use CPT codes in applies_to_codes:** Rejected — leads to retrieval of E/M coverage policies for every claim with an office visit code, regardless of whether coverage is actually in question.

### Implications

- The coverage agent v1 can only produce findings for claims with ICD-10 codes in the JSON policy corpus (currently: Z00.00, I10, Z00.01, 99395 via applies_to_codes). All other claims correctly produce no AI finding.
- `tests/test_coverage_validation.py` tests all governance paths without real API calls. Mock is applied at `agents.coverage_validation.anthropic.Anthropic` — the same boundary used for all future agent tests.
- `ANTHROPIC_MODEL` env var overrides the default model (`claude-haiku-4-5`); `claude-sonnet-4-5` or `claude-sonnet-4-6` can be selected for higher reasoning quality.

---

## ADR-013: Coverage Validation Agent v2 — Vector-First Retrieval with JSON Fallback

**Status:** Decided — implemented
**Decided:** Phase 4, Session 1D

### Context

ADR-012's "Upgrade Path" specified replacing the JSON `find_policies_by_codes()` call outright with `vector_store.query()` once Phase 4 was complete. By the time Phase 4 (Sessions 1A–1D) finished, the actual constraint was clearer: the ChromaDB index has no seeded corpus (Session 1D's scope explicitly excluded bulk CMS downloads and large-corpus seeding — see `docs/Roadmap.md` Phase 4). A hard replacement would mean every claim review produces zero coverage findings until someone manually runs ingestion against a real, populated set of LCDs/NCDs — a regression from v1's working (if limited) JSON-backed demo.

### Decision

`agents/coverage_validation.py` retrieval is now a fallback chain, not a replacement:
1. `_retrieve_from_vector_store(claim)` — builds a query from the claim's CPT/HCPCS and ICD-10 codes, queries `VectorStore.query()` (capped at `_MAX_POLICIES`). Returns `[]` if the query text is empty, the store is empty (`count() == 0`), or `query()` raises any exception.
2. `_retrieve_from_json_fallback(claim)` — the original v1 path (`find_policies_by_codes()` filtered to `source_type in {"LCD", "NCD"}`), used only when step 1 returns `[]`.
3. `_retrieve_policies(claim)` is the single entry point encoding this order; `validate_coverage()` calls only this.

Vector chunk results are converted to the same policy-dict shape (`document_id`, `title`, `section`, `effective_date`, `edition`, `excerpt`) the JSON path already produced, via `_vector_result_to_policy()`, so `_build_user_message()` and `_parse_response()` — including citation grounding (`citation_doc_id` must be in the retrieved set) — required zero changes.

### Rationale

**An empty index must not be a regression.** Falling back to JSON when the vector store has nothing means a fresh checkout, or a checkout where ingestion hasn't been run yet, behaves exactly like v1. The vector path is additive, not a cutover.

**Fallback on `count() == 0` is checked before `query()` is called**, not just on an empty/exception result from `query()` itself — this avoids embedding-model overhead (loading the ONNX model) on every claim review when the index is known to be empty, which is the common case until a corpus is seeded.

**Broad exception handling on the vector path is intentional.** Any ChromaDB failure (corrupted index, missing embedding model, disk issue) degrades to JSON rather than blocking coverage validation entirely — consistent with the project's existing pattern of never letting infrastructure failures block claim review (e.g. NPPES timeout silently skipping the NPI finding in `rules/npi.py`).

**No new governance surface.** Citation grounding, the `_MAX_POLICIES` cap, the "no retrieved policy → no AI finding" rule, the tool schema, and the audit workflow are all unchanged — the swap is purely about where `lcd_policies` comes from before reaching the existing model-call and parsing logic.

### Alternatives considered

| Option | Reason not chosen |
|---|---|
| Hard cutover to ChromaDB only (as ADR-012 originally specified) | Regresses to zero findings on any unseeded or freshly-cloned environment — worse than v1 for no governance benefit |
| Merge vector + JSON results together | Risks citing two different "shapes" of evidence for the same claim and complicates the `_MAX_POLICIES` cap; an either/or fallback is simpler to reason about and test |
| Fall back only on `query()` exception, not on `count() == 0` | Wastes the embedding-model load cost on every review while the index is empty, which is the default state until a corpus is seeded |

### TD-18 resolution as a prerequisite

Before writing the swap, live calls were made against `api.coverage.cms.gov` to validate the field-name assumptions `retrieval/ingest.py` had been built against in Session 1C (unverified at the time due to no network access). This found and fixed a real bug — CMS responses are wrapped in a `{"meta", "data": [...]}` envelope, not flat dicts — plus wrong endpoint URLs, a missing Bearer-token flow for LCD/Article, and several wrong field names. See `docs/Technical_Debt_Register.md` TD-18 (resolved) and TD-19 (new: contractor name not populated, low priority). This was necessary groundwork, not scope creep: Session 1D's vector path is only as trustworthy as the ingestion feeding it, even though the seeded-corpus question itself stayed out of scope.

### Implications

- `tests/test_coverage_validation.py` gained an autouse `mock_vector_store` fixture (default `count() == 0`) so all 14 pre-existing tests exercise the JSON fallback exactly as before, with 10 new tests added for the vector path, conversion, grounding-with-vector-doc-id, and each fallback trigger (empty list, exception, both empty).
- No real ChromaDB instance or Anthropic API call is created in any coverage_validation test.
- The ChromaDB index remains unseeded after this session — running `scripts/ingest_coverage.py` followed by `chunk_document()` + `VectorStore.index()` against a real corpus is a separate, future action, not part of this ADR.

---

## ADR-014: Sentence-Aware Chunking and Defensive Excerpt Cleanup

**Status:** Decided — implemented
**Decided:** Phase 4, Session 1D follow-up

### Context

ADR-013 made the vector path live, but it was only validated against mocked retrieval results — no real ChromaDB index had been seeded and queried end-to-end with a real Anthropic call. Doing that validation (seeding 2 real CMS documents: LCD 33431 "HbA1c", NCD 98 "Blood Glucose Testing") surfaced a real bug: `retrieval/chunking.py`'s fallback for a single paragraph exceeding `max_chunk_chars` (the common case for CMS LCD/NCD text, which is typically one long unbroken paragraph) cut text at a fixed character offset. For LCD 33431 this produced a chunk reading `"). This NCD lists the ICD-10 codes for HbA1c..."` — and because `agents/coverage_validation.py` feeds the full chunk text to the model verbatim as "the policy text" for it to quote from, the model naturally echoed that fragment into `citation_excerpt`, surfacing a broken-looking quote directly in the UI.

### Decision

Two independent fixes, addressing chunk-quality at the source and citation-quality as a backstop:

1. **`retrieval/chunking.py`**: replaced the character-offset hard split with `_split_long_paragraph()` — a sentence-boundary-aware splitter that packs whole sentences into each piece, only falling back to a hard character split if a single sentence alone exceeds `max_chunk_chars` (rare). Added defensive, idempotent HTML-entity unescape + tag stripping (`_clean_entities()`) and post-split cleanup (`_finalize_piece()`) that collapses stray whitespace and strips any leading dangling closing-punctuation/quote character. Exposed `starts_with_dangling_fragment()` and `trim_leading_fragment()` as public functions so other modules share one definition of "looks like a mid-sentence cut."
2. **`agents/coverage_validation.py`**: added `_clean_citation_excerpt()`, used when constructing `Citation.excerpt` in `_parse_response()`. If the model's own `citation_excerpt` is empty or starts with a dangling fragment character, falls back to `_sentence_snippet()` — a cleaned, sentence-bounded snippet of the actual retrieved chunk (`policy["excerpt"]`) the model was grounded in. This is deliberately a second, independent line of defense: even with clean chunking, a model can still produce a fragment on its own (paraphrase artifact, truncated quote), and this catches that case regardless of root cause.

### Rationale

**Fix the data, then guard the boundary.** The chunking fix addresses the actual root cause (most LCD/NCD text has no paragraph breaks at all, so the "rare hard-split fallback" was actually the common path for real CMS text). The excerpt-cleanup fix in the agent is defense in depth — it doesn't assume chunking is the only place a fragment can originate, since model output is inherently non-deterministic and outside this codebase's control.

**Shared, public fragment-detection logic.** `starts_with_dangling_fragment()`/`trim_leading_fragment()` live in `retrieval/chunking.py` (where the concept originates structurally) and are imported by `coverage_validation.py` rather than each module defining its own punctuation set — one definition of "dangling" can't drift between the two call sites.

**Fallback to the chunk, not to nothing.** When `_clean_citation_excerpt()` rejects the model's excerpt, it falls back to a snippet of the real retrieved text rather than an empty string — the citation should always have *some* supporting text when a chunk was actually retrieved, even if the model's own quoting attempt was bad.

### Alternatives considered

| Option | Reason not chosen |
|---|---|
| Only fix chunking, no agent-side guard | Doesn't protect against the model itself producing a fragment independent of chunk quality (paraphrase artifacts, truncated quotes) |
| Only add the agent-side guard, leave chunking's hard character split as-is | Treats the symptom, not the cause — every newly ingested long-paragraph document would keep producing fragment chunks fed to the model, relying entirely on the fallback to mask it |
| Reject the model's finding entirely if its excerpt looks like a fragment (no fallback) | Throws away an otherwise-valid finding (correct doc_id, correct grounding) over a cosmetic excerpt issue — worse for recall with no governance benefit, since citation grounding (doc_id-based) is unaffected either way |

### Validation

Re-chunked and re-indexed the two already-cached documents (no new network calls, no new documents — `scripts/ingest_coverage.py` was not re-run) with the fixed chunker: 7 chunks → 8, none starting with dangling punctuation. Ran one live `validate_coverage()` call against Scenario A's codes (CPT 80053/83036, ICD-10 Z00.00) end-to-end through the real vector store and a real Anthropic call: citation grounded to the real CMS doc (33431), excerpt read as a complete sentence, citation grounding still passed. 12 new tests (6 in `tests/test_chunking.py`, 6 in `tests/test_coverage_validation.py`) cover entity/tag cleanup, dangling-fragment detection, sentence-boundary splitting, and the excerpt-cleanup fallback (clean-excerpt-unchanged, dangling-excerpt-replaced, empty-excerpt-replaced, no-fallback-available, plus a vector-sourced grounding regression test using the exact production fragment string).

### Implications

- `retrieval/chunking.py` now does its own defensive HTML cleanup, redundant with (but independent of) `retrieval/ingest.py:_clean_html()` — intentional, since `chunk_document()` may someday receive text from a source other than `ingest.py`.
- This investigation also surfaced two debt items documented separately: TD-21 (a long-lived `VectorStore` singleton doesn't see a re-index performed by a separate process — requires an app restart) and TD-20 (raw model tool-call output and `Citation.excerpt` are never persisted, so a saved decision's literal excerpt can't be reconstructed after the fact). Neither was fixed as part of this ADR.

---

## ADR-015: Light Orchestrator Scope — Defer Documentation Review, Skip a Separate Coding Validation Agent

**Status:** Decided — implemented
**Decided:** Phase 7, "Unified Review" session

### Context

The original Phase 7 plan (see `docs/Roadmap.md` Phase 7, pre-revision) called for a full four-agent architecture: orchestrator dispatches Coverage Validation and Documentation Review in parallel, then Denial Prevention synthesizes all findings. At the time this milestone was scoped, only Coverage Validation existed; Documentation Review, Coding Validation, the orchestrator, and the denial-prevention synthesis layer were all still docstring stubs (TD-04).

A milestone-evaluation pass (6 candidate next milestones, see project history) concluded the MVP already demonstrates strong AI product value through deterministic CMS validation, real CMS RAG retrieval, the Coverage Validation Agent, citation grounding, human review, and the audit trail. The judgment was that unified review and risk synthesis — not a second LLM agent — was the higher-priority next milestone.

### Decision

Implement `agents/orchestrator.py` and `agents/denial_prevention.py` against a **light** scope: combine only the rule layer and the Coverage Validation Agent into one `RiskAssessment`. Documentation Review is not implemented and not called. No placeholder finding, no "not yet implemented" user-facing finding, and no entry in `checks_run` is fabricated for it. Coding Validation is not built as a separate LLM agent in this milestone at all — it would duplicate the rule layer's NCCI/MUE/code_validity checks.

Documentation Review remains in the product vision (PRD §9's four-agent architecture) and on the roadmap, marked "Deferred / Under Evaluation" — not removed, not abandoned, to be revisited before public release.

### Rationale

**Ship the synthesis layer now; it doesn't need to wait for every agent to exist.** `RiskAssessment(score, findings, escalation_required, checks_run)` is well-defined over "however many findings actually exist this run" — nothing about its shape requires exactly four agent sources. Building it against two sources (rules + coverage) now means Documentation Review, when it ships, is an additive call into an already-working synthesis function, not a redesign.

**A placeholder finding is worse than no finding.** A "Documentation Review: not yet implemented" finding displayed in the UI would look like a real governance signal — exactly the kind of unverifiable claim the project's "no citation → no finding" principle (ADR-002, ADR-012) exists to prevent. Silence about an unimplemented capability is honest; a fake finding about it is not.

**`checks_run` reflects what executed, not what's planned.** Consistent with the existing rule-layer `CHECKS_RUN` semantics (a clean claim still lists all 5 rule checks as run, because they ran and found nothing) — Documentation Review is absent from `checks_run` because it never executes in this milestone, the same logic by which a short-circuited claim's `checks_run` has one entry instead of six.

**Coding Validation as a separate agent is a non-goal, not a deferral.** Unlike Documentation Review (a real future capability), an LLM-based Coding Validation agent would re-litigate questions the rule layer already answers deterministically and more reliably (ADR-001). There is no future version of this agent planned; TD-04's reference to it is tracked for completeness, not as a roadmap commitment.

### Alternatives Considered

- **Implement all four agents in this milestone:** Rejected by the milestone-evaluation pass — broader AI surface area was judged lower-value right now than unified review and synthesis over what already exists.
- **Stub Documentation Review with a placeholder LOW finding ("documentation review not available"):** Rejected — looks like a real finding to a reviewer or auditor, violates the project's citation-integrity principle, and was explicitly ruled out by name in the milestone's approved scope.
- **Wait to build the orchestrator until Documentation Review also exists:** Rejected — delays the synthesis layer (`RiskAssessment`, escalation logic) for a dependency it doesn't structurally need.

### Implications

- `agents/orchestrator.py:run_review()` detects the rule-layer short-circuit via `f.rule == "npi_invalid" and f.severity == "HIGH"` — the same detection rule already used in `app/main.py:_render_checks_summary()` — to decide whether to call the coverage agent at all and what `checks_run` should contain.
- When Documentation Review is eventually implemented, it slots into `run_review()` as one more call before `denial_prevention.synthesize()`, with its own entry added to `checks_run` only when it actually executes — no change to `denial_prevention.synthesize()`'s signature or logic is anticipated.
- `tests/test_orchestrator.py` includes 3 dedicated tests (`test_no_documentation_review_placeholder_finding_ever_appears`, `test_no_coding_validation_placeholder_finding_ever_appears`, `test_no_documentation_review_label_in_checks_run`) that would fail if a future change accidentally introduced a placeholder — a regression guard for this ADR's decision, not just a coverage metric.

---

## ADR-016: Coding Validation Agent Added as a Second LLM Agent (Supersedes ADR-015's Coding Validation Framing)

**Status:** Decided — implemented
**Decided:** v1.3, "Coding Validation Agent" milestone

### Context

ADR-015 (Phase 7) judged a separate Coding Validation LLM agent a "non-goal, not a deferral," reasoning that it would re-litigate questions the deterministic rule layer (NCCI, MUE, modifiers, code validity) already answers more reliably. That reasoning is correct for the rule-layer's specific checks, but it conflated "duplicates the rule layer" with "any LLM reasoning about coding at all." There is a class of coding judgment the rule layer cannot perform because it isn't a deterministic lookup: whether a diagnosis is specific enough to defensibly support a billed procedure, whether the diagnosis-to-procedure pairing would draw payer scrutiny, and whether an alternative diagnosis code would be more defensible. This milestone scopes a second LLM agent narrowly to that reasoning gap.

ADR-015 is left unchanged (per explicit instruction for this milestone) — it remains an accurate record of the Phase 7 decision and its reasoning at the time. This ADR supersedes only the conclusion that a separate Coding Validation agent is a non-goal; it does not rewrite ADR-015's text.

### Decision

Add `agents/coding_validation.py` as a second LLM agent, structurally identical to the Coverage Validation Agent (`agents/coverage_validation.py`):

- `validate_coding(claim) -> list[Finding]`, one Anthropic call, forced `tool_choice`, two-tool schema (`report_coding_finding` / `no_coding_concern`).
- Reuses the Coverage Agent's exact retrieval path (ChromaDB vector store first, JSON `policy_examples.json` fallback) — no new corpus, no new vector store, no new retrieval architecture. The same LCD/NCD source material supports both coverage and coding reasoning; only the system prompt and tool framing differ.
- Same governance pattern: no API key → `[]`; no retrieved policy → `[]`; citation_doc_id not in the retrieved set → suppressed finding; model exception → `[]`; stable finding IDs (`"cod-"` prefix, mirroring `"cov-"`).
- The system prompt explicitly instructs the model: *"Do not identify NCCI edits, MUE violations, modifier requirements, code validity issues, or any deterministic rule-engine findings. Assume those checks have already been performed. Focus only on coding defensibility, diagnosis specificity, diagnosis-to-procedure support, and payer scrutiny risk."* This is the boundary ADR-015 was protecting — the rule layer's deterministic checks are explicitly off-limits to this agent's reasoning, not duplicated.
- `agents/orchestrator.py` calls `validate_coding()` sequentially after `validate_coverage()` (no parallel execution), and `agents/denial_prevention.py:synthesize()` grows a third `coding_findings` parameter, combined into `RiskAssessment` identically to coverage findings.

### Rationale

**The rule layer vs. LLM-reasoning boundary is about determinism, not topic.** ADR-001's original principle is "deterministic lookups stay in the rule layer; LLM reasoning is for judgment the rule layer can't make." Diagnosis specificity and payer-scrutiny risk are judgment calls about defensibility, not lookups against a quarterly CSV — they were always in-scope for an LLM agent under ADR-001; ADR-015 incorrectly extended the "non-goal" framing to all coding-adjacent reasoning rather than just the rule-layer's specific deterministic checks.

**Reusing Coverage Agent's exact architecture and retrieval avoids a second governance surface.** Citation grounding, the "no citation → no finding" rule, error handling, and finding-ID stability are already correct and tested in the Coverage Agent. Mirroring that pattern exactly (rather than inventing a new one) means the new agent inherits proven governance instead of re-deriving it.

**`synthesize()`'s signature growing to three finding lists was anticipated, not a redesign.** ADR-015 explicitly predicted Documentation Review would "slot in as one more call... no change to `synthesize()`'s signature or logic is anticipated" beyond an added parameter — the same shape of change applies here for Coding Validation.

### Alternatives Considered

- **Extend the Coverage Agent's prompt to also reason about coding defensibility:** Rejected — conflates two distinct reviewer responsibilities (medical necessity vs. coding defensibility) into one prompt and one finding stream, making it harder to reason about which agent is responsible for which class of finding, and harder to evolve the two independently.
- **Build a new retrieval path or corpus specific to coding guidance:** Rejected per this milestone's explicit constraint — the existing LCD/NCD corpus already contains the policy text relevant to both coverage and coding reasoning; a second corpus would duplicate ingestion/retrieval machinery for no retrieval-quality gain.
- **Run Coverage and Coding agents in parallel:** Rejected per this milestone's explicit constraint — sequential execution keeps the orchestrator a simple deterministic controller (no thread/async coordination) and the cost/latency difference is not a concern at this MVP scale.

### Implications

- `tests/test_orchestrator.py`'s `test_no_coding_validation_placeholder_finding_ever_appears` (added under ADR-015) is removed — it asserted no `coding_validation`-rule finding ever appears, which is now false by design. Its regression-guard intent (no fabricated finding for an unimplemented capability) is superseded by real test coverage of the now-implemented agent in `tests/test_coding_validation.py` and `tests/test_orchestrator.py`'s new "Coding agent integration" tests.
- `tests/test_orchestrator.py`'s Documentation-Review-specific placeholder guards are unaffected and remain accurate — Documentation Review is still deferred.
- `docs/Technical_Debt_Register.md` TD-04 narrows further: only `agents/documentation_review.py` remains an unimplemented stub.

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
| Light orchestrator (defer Documentation Review) | ✅ Ships synthesis sooner | ✅ No fabricated findings | ✅ Honest "not implemented" via absence, not a fake finding | ✅ Additive when Documentation Review ships |
| Coding Validation Agent reuses Coverage Agent's retrieval | ✅ No new corpus/vector store to build | ✅ Inherits proven citation grounding | ✅ Same governance pattern as Coverage Agent | ✅ Sequential, additive — no orchestrator redesign |
