# Denial Prevention Copilot

Agentic pre-submission claim review that catches denial risks before a claim leaves the building. Four specialized agents validate coding, coverage, documentation, and synthesize a denial risk score — every finding backed by a cited source. Humans make every final call.

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

See `docs/PRD_Agentic_Claims_Review_and_Denial_Prevention_Copilot.pdf` for the full product spec. High-level: deterministic rule checks (rules/) run before any LLM call; agents (agents/) run in parallel via the orchestrator; findings are grounded in retrieved LCD/NCD text (retrieval/); all decisions land in an immutable audit log (db/).
