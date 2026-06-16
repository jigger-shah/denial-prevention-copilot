"""
NPI Registry API client (NPPES).

Validates NPI format and active enrollment via the CMS NPPES public REST API.

Validation flow:
  1. Empty NPI → no finding (field is optional for this MVP).
  2. Non-numeric or not exactly 10 digits → HIGH finding (invalid format).
  3. 10-digit but fails Luhn check digit → HIGH finding (structurally invalid).
  4. Luhn-valid, NPPES returns 0 results → MEDIUM finding (NPI not enrolled).
  5. Luhn-valid, NPPES returns active provider (status "A") → no finding.
  6. NPPES timeout or network error → no finding (claim review continues).

Luhn algorithm for NPI (CMS specification):
  Prepend "80840" to the 10-digit NPI, producing a 15-character payload.
  Apply standard Luhn: from the rightmost digit, double every second digit;
  subtract 9 from any doubled value > 9; sum all digits; valid if sum % 10 == 0.

NPPES endpoint: https://npiregistry.cms.hhs.gov/api/?number={npi}&version=2.1
Timeout: 2 seconds. Network failures are silenced — review is never blocked.

Source: CMS NPPES NPI Registry public API.
Refresh cadence: live (queried at review time; no local cache).
"""

from __future__ import annotations

from dataclasses import replace

import requests

from rules.models import ClaimIn, Citation, Finding

_NPPES_URL = "https://npiregistry.cms.hhs.gov/api/"
_TIMEOUT = 2  # seconds

_BASE_CITATION = Citation(
    source="NPPES",
    doc_id="NPPES_NPI_REGISTRY",
    section="Provider Enumeration Validation",
    edition="API v2.1",
    effective_date=None,
    excerpt=None,
)


def luhn_valid(npi: str) -> bool:
    """
    Return True if the 10-digit NPI passes the CMS Luhn check-digit test.

    Prepends "80840" per CMS NPI enumeration standards, then applies the
    standard Luhn algorithm. Returns False for non-numeric or non-10-digit input.
    """
    if not npi.isdigit() or len(npi) != 10:
        return False
    payload = "80840" + npi
    total = 0
    for i, ch in enumerate(reversed(payload)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def lookup_nppes(npi: str) -> dict | None:
    """
    Query the NPPES NPI Registry for the given NPI.

    Returns the first result dict if found (result_count > 0), or None if the
    NPI is not enrolled (result_count == 0).

    Raises requests.RequestException (or subclasses) on timeout, network error,
    or HTTP error — callers that want silent failure should catch Exception.
    """
    resp = requests.get(
        _NPPES_URL,
        params={"number": npi, "version": "2.1"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("result_count", 0) > 0:
        return data["results"][0]
    return None


def check_npi(claim: ClaimIn) -> list[Finding]:
    """
    Validate the claim's NPI and return 0–1 Findings.

    An empty NPI is treated as omitted — the field is optional for this MVP.
    A HIGH finding is returned for format and Luhn failures; these short-circuit
    the rule engine so downstream coding checks do not run (invalid provider
    identity makes code-level checks unreliable).
    A MEDIUM finding is returned when NPPES cannot confirm the NPI is active.
    No finding is returned on NPPES timeout or network failure.
    """
    npi = (claim.npi or "").strip()
    if not npi:
        return []

    # Format check: must be exactly 10 digits
    if not npi.isdigit() or len(npi) != 10:
        return [Finding(
            rule="npi_invalid",
            severity="HIGH",
            issue=f"NPI '{npi}' is not a valid 10-digit number.",
            recommendation=(
                "Correct the NPI to exactly 10 digits before submitting. "
                "Valid NPIs are numeric only."
            ),
            citation=replace(
                _BASE_CITATION,
                excerpt=(
                    f"NPI '{npi}' failed format validation: must be exactly 10 digits, "
                    "numeric only, per CMS NPI enumeration standards."
                ),
            ),
            confidence=0.99,
        )]

    # Luhn check digit
    if not luhn_valid(npi):
        return [Finding(
            rule="npi_invalid",
            severity="HIGH",
            issue=f"NPI {npi} fails check-digit validation (Luhn algorithm).",
            recommendation=(
                "Verify the NPI was entered correctly. The check digit (last digit) "
                "does not match the CMS Luhn formula. "
                "Look up the correct NPI at npiregistry.cms.hhs.gov."
            ),
            citation=replace(
                _BASE_CITATION,
                excerpt=(
                    f"NPI {npi} has an invalid check digit under the Luhn algorithm "
                    "(80840 prefix per CMS NPI specification). "
                    "This NPI is structurally invalid and will be rejected by CMS."
                ),
            ),
            confidence=0.99,
        )]

    # NPPES registry lookup — network/timeout errors are silenced so review is never blocked
    try:
        result = lookup_nppes(npi)
    except Exception:
        return []

    if result is None:
        return [Finding(
            rule="npi_registry",
            severity="MEDIUM",
            issue=f"NPI {npi} was not found in the NPPES registry.",
            recommendation=(
                "Verify the NPI is enrolled and active in NPPES before submitting. "
                "Search at npiregistry.cms.hhs.gov."
            ),
            citation=replace(
                _BASE_CITATION,
                excerpt=(
                    f"NPI {npi} returned 0 results from the NPPES NPI Registry "
                    "(API v2.1). The provider may not be enrolled, or the NPI "
                    "may have been entered incorrectly."
                ),
            ),
            confidence=0.80,
        )]

    status = result.get("basic", {}).get("status", "")
    if status != "A":
        return [Finding(
            rule="npi_registry",
            severity="MEDIUM",
            issue=f"NPI {npi} is not active in NPPES (status: {status or 'unknown'}).",
            recommendation=(
                "Verify the provider's NPPES enrollment status. "
                "A deactivated or replaced NPI causes an automatic denial at CMS payers."
            ),
            citation=replace(
                _BASE_CITATION,
                excerpt=(
                    f"NPI {npi} found in NPPES with status '{status}'. "
                    "Active status 'A' is required for claim submission."
                ),
            ),
            confidence=0.85,
        )]

    return []
