"""
Claim review orchestrator.

Deterministic Python controller — not a free-running LLM loop. Sequence:
  1. Validate claim schema (Pydantic).
  2. Run rules/ layer synchronously: NPI lookup, code validity, NCCI PTP pairs, MUE limits.
     Any hard rule failure (e.g. invalid NPI) short-circuits the agent pass and returns
     immediately with a structured error finding.
  3. Dispatch CodingValidationAgent, CoverageValidationAgent, and DocumentationReviewAgent
     in parallel (asyncio or ThreadPoolExecutor).
  4. Collect Finding lists from each agent; pass the combined set to DenialPreventionAgent
     for risk synthesis and scoring.
  5. If aggregate confidence is below CONFIDENCE_THRESHOLD, mark the claim for human-first
     queue rather than presenting uncertain recommendations as confident ones.
  6. Persist findings and metadata to db.audit.
  7. Return the risk assessment to the caller (app/main.py).

All LLM calls use structured tool use so every response is validated against the
Finding schema — the orchestrator never parses free-form LLM text.
"""
