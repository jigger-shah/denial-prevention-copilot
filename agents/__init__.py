"""
Agent layer for the Denial Prevention Copilot.

All agents receive a ClaimContext (Pydantic model) and return a list of Finding
objects. The orchestrator coordinates execution order: deterministic rule checks
(rules/) run first, then agents run in parallel, and finally the denial prevention
agent synthesizes the findings into a risk assessment.
"""
