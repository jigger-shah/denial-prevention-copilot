"""
Audit log view component.

Queries db.audit for the decision trail of a single claim and renders it as a
timeline: inputs → deterministic check results → agent findings with citations →
human decisions (accept / modify / override + reason + timestamp + user).
Provides a "Export to CSV" button that calls db.audit.export_claim_log().
"""
