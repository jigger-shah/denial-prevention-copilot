# Denial Prevention Copilot

Agentic pre-submission claim review that catches denial risks before a claim leaves the building. A deterministic rule layer (NCCI, MUE, NPI, code validity) and two citation-grounded LLM agents — Coverage Validation (medical necessity) and Coding Validation (diagnosis specificity, coding defensibility, payer scrutiny risk) — feed a single Unified Review that synthesizes a denial risk score. Every AI finding is backed by a cited LCD/NCD source. Humans make every final call.

A Documentation Review Agent remains part of the product vision and roadmap but is currently deferred (not implemented, not required for this MVP) — see `docs/Roadmap.md` Phase 6.

Built on free public data: NPPES NPI Registry, CMS Coverage API (NCDs/LCDs), NCCI PTP and MUE files, the real CMS ICD-10-CM order file, HCPCS Level II. Synthetic claims only — no PHI.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
```

## Run

```bash
streamlit run app/main.py
```

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

## Architecture

See `docs/PRD_Agentic_Claims_Review_and_Denial_Prevention_Copilot.pdf` for the full product spec. High-level: deterministic rule checks (`rules/`) run before any LLM call, with a HIGH NPI finding short-circuiting downstream checks; the orchestrator (`agents/orchestrator.py`) then calls the Coverage Validation Agent and the Coding Validation Agent sequentially and synthesizes all three sources into one `RiskAssessment` (`agents/denial_prevention.py`) — no LLM call in synthesis; both agents' findings are grounded in retrieved LCD/NCD text (`retrieval/`), reusing the same retrieval path with different reasoning prompts; all decisions land in an immutable audit log (`db/`). A standalone golden-set evaluation harness (`evaluation/`) runs the same orchestrator end-to-end against labelled synthetic claims to measure precision/recall/F1 by category. ICD-10-CM diagnosis codes are validated against the real CMS ICD-10-CM order file (`rules/icd10_loader.py`, `rules/icd10.py`) for code existence and unspecified-diagnosis detection — see `docs/Roadmap.md` Phase 8.5.
