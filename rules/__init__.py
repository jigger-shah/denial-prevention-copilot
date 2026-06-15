"""
Deterministic rule layer.

All checks here are pure lookups or rule evaluations — no LLM involvement.
The orchestrator runs this layer synchronously before dispatching any agents,
so a hard rule failure can short-circuit the more expensive agent pass.
"""
