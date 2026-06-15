"""
NCCI MUE (Medically Unlikely Edit) table lookups.

Ingests the CMS quarterly MUE adjudication indicator (MAI) files from
data/reference/ and exposes a lookup function that, given a HCPCS/CPT code
and a reported unit count, returns:
  - The MUE unit limit for that code.
  - The MAI (1 = line edit, 2 = date of service edit, 3 = date of service
    edit with clinical rationale required).
  - Whether the reported units exceed the limit.

MAI=1 is a hard per-line denial trigger; MAI=2/3 limits apply across all lines
for the same date of service and may be bypassable with documentation.

Source: CMS NCCI MUE files.
Refresh cadence: quarterly.
"""
