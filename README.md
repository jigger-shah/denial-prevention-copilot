# Denial Prevention Copilot

Agentic pre-submission claim review that catches denial risks before a claim leaves the building. A deterministic rule layer (NCCI, MUE, NPI, code validity) and a citation-grounded Coverage Validation Agent feed a single Unified Review that synthesizes a denial risk score — every AI finding backed by a cited LCD/NCD source. Humans make every final call.

A Documentation Review Agent remains part of the product vision and roadmap but is currently deferred (not implemented, not required for this MVP) — see `docs/Roadmap.md` Phase 6.

Built on free public data: NPPES NPI Registry, CMS Coverage API (NCDs/LCDs), NCCI PTP and MUE files, ICD-10-CM, HCPCS Level II. Synthetic claims only — no PHI.

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

## Architecture

See `docs/PRD_Agentic_Claims_Review_and_Denial_Prevention_Copilot.pdf` for the full product spec. High-level: deterministic rule checks (`rules/`) run before any LLM call, with a HIGH NPI finding short-circuiting downstream checks; the orchestrator (`agents/orchestrator.py`) then calls the Coverage Validation Agent and synthesizes both into one `RiskAssessment` (`agents/denial_prevention.py`) — no LLM call in synthesis; coverage findings are grounded in retrieved LCD/NCD text (`retrieval/`); all decisions land in an immutable audit log (`db/`).
