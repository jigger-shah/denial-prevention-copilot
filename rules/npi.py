"""
NPI Registry API client (NPPES).

Queries the CMS NPPES NPI Registry REST API in real time to validate:
  - NPI is a valid 10-digit number with correct check digit (Luhn algorithm).
  - NPI exists in the registry and is active (not deactivated or replaced).
  - Provider taxonomy code(s) and whether the taxonomy is appropriate for the
    billed place of service and procedure type.

Returns an NPIResult(npi, is_valid, is_active, name, taxonomy_codes, error)
Pydantic model. A deactivated NPI is a hard denial trigger at most payers.

Source: NPPES NPI Registry public API.
Refresh cadence: live (queried at review time).
"""
