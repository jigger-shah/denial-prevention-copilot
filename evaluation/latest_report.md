# Golden Set Evaluation Report

Generated: 2026-06-19 03:44 UTC
Mode: **offline** — Coverage/Coding Agent calls mocked to return no findings; their categories below reflect that, not agent accuracy. Run with --live for a real read.
Claims evaluated: 14

## Metrics

| Category | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| Overall | 16 | 0 | 6 | 1.00 | 0.73 | 0.84 |
| Rule Engine | 16 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| Coverage Agent | 0 | 0 | 3 | 0.00 | 0.00 | 0.00 |
| Coding Agent | 0 | 0 | 3 | 0.00 | 0.00 | 0.00 |

## Claim-level results

| Claim | Expected | Actual | TP | FP | FN |
|---|---|---|---|---|---|
| GOLD-001 | invalid_npi | invalid_npi | 1 | 0 | 0 |
| GOLD-002 | invalid_npi | invalid_npi | 1 | 0 | 0 |
| GOLD-003 | ncci_conflict | ncci_conflict | 1 | 0 | 0 |
| GOLD-004 | mue_limit | mue_limit | 1 | 0 | 0 |
| GOLD-005 | missing_modifier_25 | missing_modifier_25 | 1 | 0 | 0 |
| GOLD-006 | diagnosis_procedure_mismatch | diagnosis_procedure_mismatch | 1 | 0 | 0 |
| GOLD-007 | diagnosis_procedure_mismatch, missing_modifier_25, mue_limit, ncci_conflict | diagnosis_procedure_mismatch, missing_modifier_25, mue_limit, ncci_conflict | 4 | 0 | 0 |
| GOLD-008 | (none) | (none) | 0 | 0 | 0 |
| GOLD-009 | (none) | (none) | 0 | 0 | 0 |
| GOLD-010 | coverage_medical_necessity | (none) | 0 | 0 | 1 |
| GOLD-011 | coding_defensibility | (none) | 0 | 0 | 1 |
| GOLD-012 | coverage_medical_necessity, ncci_conflict | ncci_conflict | 1 | 0 | 1 |
| GOLD-013 | coding_defensibility, missing_modifier_25 | missing_modifier_25 | 1 | 0 | 1 |
| GOLD-014 | coding_defensibility, coverage_medical_necessity, diagnosis_procedure_mismatch, missing_modifier_25, mue_limit, ncci_conflict | diagnosis_procedure_mismatch, missing_modifier_25, mue_limit, ncci_conflict | 4 | 0 | 2 |
