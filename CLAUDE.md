# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
source .venv/bin/activate
pip install -r requirements.txt

# Run the app
streamlit run app/main.py

# Run all tests
pytest tests/

# Run only deterministic rule tests (no LLM, no live APIs)
pytest tests/test_rules.py

# Run only golden-set evaluation (precision/recall against labelled claims)
pytest tests/ -m golden
```

Set `ANTHROPIC_API_KEY` in a `.env` file at the repo root. The app reads it via `python-dotenv`.

## Architecture

The system separates deterministic work from generative work by design. The rule layer (`rules/`) always runs first and handles lookups that can be answered without an LLM. Agents (`agents/`) only run after the rule layer completes.

### Data flow

```
Claim intake (app/) → orchestrator.py
  → rules/ (NPI, code validity, NCCI PTP, MUE)   ← synchronous, short-circuits on hard failure
  → agents/ (coding, coverage, docs) in parallel  ← LLM-backed, structured tool use
  → denial_prevention.py (synthesis, risk score)  ← deterministic over structured Finding objects
  → db/audit.py (immutable write)
  → app/ (findings panel, human decision)
```

### Key design constraints from the PRD

- **No citation → no finding.** Coverage and policy findings must carry a retrieved source (document_id, section, effective_date from the LCD/NCD text). If the retrieval layer can't support a claim, suppress it.
- **Rule layer before LLM, always.** NCCI edits, MUE limits, code validity, and NPI status are deterministic lookups — never re-implement these as LLM reasoning.
- **Orchestrator is a Python controller, not an agent loop.** It dispatches agents and aggregates findings deterministically; it does not let agents call each other or spawn sub-agents.
- **Audit log is append-only.** `db/audit.py` writes only INSERT. No UPDATE or DELETE.
- **Synthetic data only.** No PHI anywhere in the codebase or data files.

### Module responsibilities

| Module | Responsibility |
|---|---|
| `agents/orchestrator.py` | Dispatch coordination, parallel agent execution, confidence-based escalation |
| `agents/coding_validation.py` | NCCI PTP pairs, MUE limits, modifier logic — deterministic lookups + rule interpretation |
| `agents/coverage_validation.py` | RAG over LCD/NCD chunks → LLM reasoning → cited medical necessity findings |
| `agents/documentation_review.py` | LLM analysis of clinical note text for E/M support and specificity |
| `agents/denial_prevention.py` | Deterministic synthesis of all findings into a RiskAssessment, no LLM call |
| `rules/ncci.py` | NCCI PTP edit table lookups (quarterly CSV from CMS) |
| `rules/mue.py` | MUE table lookups with MAI-aware severity (quarterly CSV from CMS) |
| `rules/npi.py` | Live NPPES NPI Registry API client, Luhn check digit validation |
| `rules/code_validity.py` | ICD-10-CM, CPT, HCPCS Level II validity and specificity checks |
| `retrieval/ingest.py` | Fetch LCD/NCD documents from CMS Coverage API, save to data/reference/coverage/ |
| `retrieval/chunking.py` | Section-aware splitting that keeps LCD policy sections intact for citation integrity |
| `retrieval/vector_store.py` | ChromaDB interface: index chunks, query by dx/procedure pair |
| `db/schema.py` | Pydantic models (ClaimIn, Finding, Decision, RiskAssessment) and SQLite DDL |
| `db/audit.py` | Append-only audit log read/write/export |

### Pydantic models

`Finding` is the shared contract between rules, agents, and the UI:
```python
Finding(source_agent, severity, issue, recommended_fix, citation_doc_id,
        citation_section, citation_effective_date, confidence)
```

`RiskAssessment` is what the orchestrator returns to the UI:
```python
RiskAssessment(score, findings, escalation_required, checks_run)
```

### Reference data refresh cadence

| Source | Cadence | Module |
|---|---|---|
| NCCI PTP edits | Quarterly | `rules/ncci.py` |
| NCCI MUE tables | Quarterly | `rules/mue.py` |
| HCPCS Level II | Quarterly | `rules/code_validity.py` |
| ICD-10-CM | Annual (October) | `rules/code_validity.py` |
| CMS LCD/NCD | On-demand | `retrieval/ingest.py` |
| NPPES NPI | Live (real-time API) | `rules/npi.py` |

Reference files are excluded from git (see `.gitignore`). Citation outputs must include the file edition/version so findings are traceable to the exact policy snapshot consulted.

### LLM integration

Use the Anthropic SDK (`anthropic` package) with structured tool use. Claude model: default to `claude-sonnet-4-6` for agent calls (balance of reasoning quality and latency). Coverage validation is the most demanding reasoning task; documentation review is lighter. Never call the LLM in the rule layer.
