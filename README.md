# Denial Prevention Copilot

A portfolio / demo project: agentic pre-submission claim review that catches denial risks before a claim leaves the building. A deterministic rule layer (NCCI, MUE, NPI, code validity) and two citation-grounded LLM agents — Coverage Validation (medical necessity) and Coding Validation (diagnosis specificity, coding defensibility, payer scrutiny risk) — feed a single Unified Review that synthesizes a denial risk score. Every AI finding is backed by a cited LCD/NCD source. Humans make every final call.

A Documentation Review Agent remains part of the product vision and roadmap but is currently deferred (not implemented, not required for this MVP) — see `docs/Roadmap.md` Phase 6.

Built on free public data: NPPES NPI Registry, CMS Coverage API (NCDs/LCDs), NCCI PTP and MUE files, the real CMS ICD-10-CM order file. HCPCS Level II is recognized via a small curated common-code set, not a full reference-file loader (see `docs/Technical_Debt_Register.md` TD-06). **Synthetic data only — no PHI, no real claims.**

> **Not for clinical or billing use.** This is a synthetic-data prototype demonstrating an architecture pattern, not production healthcare software. It is not HIPAA certified and has not been validated against real claims, real payer adjudication, or real patient data. Do not use it to make actual coverage, coding, or billing decisions.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional — see "AI features" below
```

## Run

```bash
streamlit run app/main.py
```

The app runs fully on a fresh clone with no `ANTHROPIC_API_KEY` — no setup beyond `pip install` is required to launch it or to use the deterministic rule-engine review (NCCI, MUE, NPI, code validity). See **AI features** below for what changes with a key.

## AI features (optional, requires your own API key)

The Coverage Validation and Coding Validation agents call the Anthropic API and need your own `ANTHROPIC_API_KEY`. Without a key:

- The sidebar and in-page AI sections show **"⚠ AI Agents Disabled"** — the app never attempts an Anthropic call and never constructs an Anthropic client.
- The deterministic rule-engine review (NCCI, MUE, NPI, code validity) remains fully available.
- Three designated sample claims display **pre-generated, clearly labeled** ("📋 Pre-generated demonstration results") AI findings captured from a real run, so you can preview representative agent output without making a live API call. See `docs/Demo_Script.md`.

To enable live AI analysis:

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

Once set, the sidebar shows **"✅ AI enabled"** and both agents run as part of "Run Full Review."

## Test

```bash
pytest tests/
```

## Evaluate

A golden-set evaluation harness measures finding precision/recall/F1 against a labelled set of synthetic claims:

```bash
python -m evaluation.run_evaluation          # offline — no Anthropic calls, rule layer measured for real
python -m evaluation.run_evaluation --live    # real Coverage/Coding Agent calls (claude-haiku-4-5)
```

Saves `latest_report.md`, `latest_results.json`, and `latest_summary.json` to `evaluation/`. See `docs/Roadmap.md` Phase 8 and `docs/Technical_Debt_Register.md` TD-09/TD-24 for current results and known gaps (agent-layer precision needs calibration before citing live numbers).

## Architecture Overview

Full product spec: `docs/PRD_Agentic_Claims_Review_and_Denial_Prevention_Copilot.pdf`.

```
Claim intake (app/) → orchestrator.py
  → rules/ (NPI, code validity, NCCI PTP, MUE)   ← synchronous, short-circuits on hard failure
  → agents/ (coverage, coding) sequentially       ← LLM-backed, skipped entirely with no API key
  → denial_prevention.py (synthesis, risk score)  ← deterministic over structured Finding objects
  → db/audit.py (immutable write)
  → app/ (findings panel, human decision)
```

**Rule Layer** (`rules/`) — always runs first, no LLM call:
- `rules/npi.py` — live NPPES NPI Registry lookup, Luhn check-digit validation; a HIGH invalid-NPI finding short-circuits everything downstream
- `rules/ncci.py` — NCCI PTP procedure-bundling edits, loaded from real CMS quarterly files (small synthetic fallback if the files aren't present locally — see `rules/data_source_status.py` for a programmatic real-data-vs-fallback check, TD-27)
- `rules/mue.py` — MUE unit limits, MAI-aware severity
- `rules/code_validity.py` — diagnosis-to-procedure conflict and modifier rules (25, 76/77 repeat-procedure, 50 bilateral)
- `rules/icd10.py` / `rules/icd10_loader.py` — ICD-10-CM code validity and unspecified-diagnosis detection against the real CMS order file
- `rules/hcpcs.py` — HCPCS Level II format recognition against a small curated common-code set (not a full reference-file loader — see `docs/Technical_Debt_Register.md` TD-06)

**AI Layer** (`agents/`) — only runs if `ANTHROPIC_API_KEY` is set:
- `agents/coverage_validation.py` — RAG over LCD/NCD chunks → LLM reasoning → cited medical-necessity findings
- `agents/coding_validation.py` — LLM coding-defensibility review (diagnosis specificity, payer scrutiny risk)
- `agents/documentation_review.py` — deferred, not implemented (see `docs/Roadmap.md` Phase 6)
- `agents/run_logger.py` — structured local logging (timestamp, claim_id, agent, finding_count, success, latency_ms) for each check the orchestrator dispatches

**Orchestration:**
- `agents/orchestrator.py` — Python controller, not an agent loop: runs the rule layer, gates the two agents on both the NPI short-circuit and key presence, then passes everything to synthesis. Agents never call each other or spawn sub-agents.
- `agents/denial_prevention.py` — deterministic synthesis of all findings into a `RiskAssessment` — no LLM call here.
- `db/audit_repository.py` — append-only audit log (INSERT only, no UPDATE/DELETE) for every human Accept/Override decision.

**Evaluation:**
- `evaluation/` — a golden-set harness that runs the same orchestrator end-to-end against labelled synthetic claims and reports precision/recall/F1 per finding category, in both offline (no API calls) and live modes.

Citation grounding is the load-bearing constraint throughout: an AI finding with no retrieved source is suppressed, never displayed.
