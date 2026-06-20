# Golden Set Evaluation Report

Generated: 2026-06-20 00:07 UTC
Mode: **live**
Claims evaluated: 15

## Metrics

| Category | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| Overall | 23 | 2 | 4 | 0.92 | 0.85 | 0.88 |
| Rule Engine | 18 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| Coverage Agent | 2 | 0 | 2 | 1.00 | 0.50 | 0.67 |
| Coding Agent | 3 | 2 | 2 | 0.60 | 0.60 | 0.60 |

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
| GOLD-008 | coding_defensibility, coverage_medical_necessity | coding_defensibility, coverage_medical_necessity | 2 | 0 | 0 |
| GOLD-009 | coding_defensibility, unspecified_diagnosis | coding_defensibility, unspecified_diagnosis | 2 | 0 | 0 |
| GOLD-010 | coverage_medical_necessity | coding_defensibility, coverage_medical_necessity | 1 | 1 | 0 |
| GOLD-011 | coding_defensibility, unspecified_diagnosis | unspecified_diagnosis | 1 | 0 | 1 |
| GOLD-012 | coverage_medical_necessity, ncci_conflict | coding_defensibility, ncci_conflict | 1 | 1 | 1 |
| GOLD-013 | coding_defensibility, missing_modifier_25 | coding_defensibility, missing_modifier_25 | 2 | 0 | 0 |
| GOLD-014 | coding_defensibility, coverage_medical_necessity, diagnosis_procedure_mismatch, missing_modifier_25, mue_limit, ncci_conflict | diagnosis_procedure_mismatch, missing_modifier_25, mue_limit, ncci_conflict | 4 | 0 | 2 |
| GOLD-015 | (none) | (none) | 0 | 0 | 0 |
