# Synthetic Claims

Synthetic claim files for development and golden-set evaluation. No PHI anywhere in this directory.

Each CSV row is one claim header. Column schema matches the `ClaimIn` Pydantic model in `db/schema.py`.

Subdirectory convention:
- `golden/`  — labelled claims with known correct findings, used for precision/recall tracking.
- `batch/`   — larger unlabelled sets for UI batch-review testing.

All NPIs, patient identifiers, and clinical scenarios are fictitious.
