"""
Claim intake form component.

Renders input fields for all claim attributes required for pre-submission review:
payer, rendering NPI, CPT/HCPCS codes (multi-value), ICD-10 diagnosis codes
(multi-value), modifiers, place of service, and units per procedure line.
Also handles CSV upload for batch review mode, validating column headers against
the expected schema before passing rows to the orchestrator.
"""
