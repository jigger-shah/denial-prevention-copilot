# Reference Data

Downloaded CMS reference files. All files are public domain; no PHI.

Files are excluded from git (see .gitignore) because they are large and refreshed on a schedule.
Run the appropriate ingestion script to populate this directory:

| File pattern              | Source                        | Cadence   |
|---------------------------|-------------------------------|-----------|
| ncci_ptp_*.csv            | CMS NCCI PTP edit tables      | Quarterly |
| ncci_mue_*.csv            | CMS NCCI MUE tables           | Quarterly |
| icd10cm_*.csv             | CMS ICD-10-CM tabular file    | Annual (Oct) |
| hcpcs_*.csv               | CMS HCPCS Level II            | Quarterly |
| coverage/                 | CMS MCD API (LCD/NCD JSON)    | On-demand |
