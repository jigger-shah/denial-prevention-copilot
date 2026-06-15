"""
Findings panel component.

Displays the orchestrator's structured findings list after agent review.
Each finding card shows: severity badge (HIGH / MEDIUM / LOW), issue description,
recommended fix, citation (source document + section + effective date), and
confidence score. Cards expand to show the raw retrieved policy excerpt.

Renders Accept / Modify / Override controls per finding. Override requires a
free-text reason before it can be submitted. All decisions are passed back to
db.audit for persistence.
"""
