"""
Manual claim intake helpers — no Streamlit rendering logic here.

Functions here are unit-testable without a running Streamlit app.
Transformation and validation logic is separated from UI code per the architecture constraint.
"""

PAYER_ID_MAP: dict[str, str] = {
    "Medicare": "MEDICARE",
    "Medicaid": "MEDICAID",
    "Blue Cross Blue Shield (BCBS)": "BCBS",
    "Aetna": "AETNA",
    "UnitedHealthcare": "UHC",
    "Cigna": "CIGNA",
    "Humana": "HUMANA",
    "Commercial - Other": "",
    "Other": "",
}

WORKED_EXAMPLE: dict = {
    "claim_id": "CLM-MANUAL-001",
    "payer_name": "Medicare",
    "provider_specialty": "Internal Medicine",
    "npi": "",
    "note_text": "",
    "service_lines": [
        {
            "cpt": "99214", "mod1": "", "mod2": "",
            "icd10_1": "Z00.00", "icd10_2": "", "icd10_3": "", "icd10_4": "",
        },
        {
            "cpt": "80053", "mod1": "", "mod2": "",
            "icd10_1": "Z00.00", "icd10_2": "", "icd10_3": "", "icd10_4": "",
        },
        {
            "cpt": "80048", "mod1": "", "mod2": "",
            "icd10_1": "Z00.00", "icd10_2": "", "icd10_3": "", "icd10_4": "",
        },
    ],
}


def get_payer_id(payer_name: str) -> str:
    """Return the standard payer ID for a display name, empty string for unknowns."""
    return PAYER_ID_MAP.get(payer_name, "")


def validate_npi(npi: str) -> tuple[bool, str]:
    """
    Validate the optional NPI field.

    Returns (is_valid, error_message). An empty NPI is valid — the field is optional.
    Luhn check-digit validation is deferred to Phase 3.
    """
    if not npi:
        return True, ""
    if not npi.isdigit():
        return False, "NPI must contain digits only."
    if len(npi) != 10:
        return False, "NPI must be exactly 10 digits."
    return True, ""


def normalize_code(code: str) -> str:
    """Strip whitespace and uppercase a code string."""
    return code.strip().upper()


def build_manual_claim(header: dict, service_lines: list[dict]) -> dict:
    """
    Convert service-line grid entries into a claim dict compatible with load_claim().

    header keys: claim_id, payer_name, payer_id, npi, provider_specialty, note_text
    service_line keys: cpt, mod1, mod2, icd10_1, icd10_2, icd10_3, icd10_4

    Returns a claim dict with:
    - Flat cpt_codes, icd10_codes, modifiers arrays for the rule engine
      (normalized, blank-filtered, deduplicated, preserving first-seen order)
    - service_lines preserved for display
    - Both payer_name/payer_id (forward compat) and payer=payer_name (backward compat
      with load_claim which reads claim_dict.get("payer"))
    """
    cpt_seen: set[str] = set()
    dx_seen: set[str] = set()
    mod_seen: set[str] = set()
    cpt_codes: list[str] = []
    icd10_codes: list[str] = []
    modifiers: list[str] = []
    normalized_lines: list[dict] = []

    for line in service_lines:
        cpt = normalize_code(line.get("cpt", ""))
        mod1 = normalize_code(line.get("mod1", ""))
        mod2 = normalize_code(line.get("mod2", ""))
        dx_slots = [normalize_code(line.get(f"icd10_{i}", "")) for i in range(1, 5)]

        normalized_lines.append({
            "cpt": cpt,
            "mod1": mod1,
            "mod2": mod2,
            "icd10_1": dx_slots[0],
            "icd10_2": dx_slots[1],
            "icd10_3": dx_slots[2],
            "icd10_4": dx_slots[3],
        })

        if cpt and cpt not in cpt_seen:
            cpt_codes.append(cpt)
            cpt_seen.add(cpt)
        for dx in dx_slots:
            if dx and dx not in dx_seen:
                icd10_codes.append(dx)
                dx_seen.add(dx)
        for mod in (mod1, mod2):
            if mod and mod not in mod_seen:
                modifiers.append(mod)
                mod_seen.add(mod)

    payer_name = header.get("payer_name", "")
    payer_id = header.get("payer_id", "").strip() or get_payer_id(payer_name)
    claim_id = header.get("claim_id", "").strip() or "CLM-MANUAL"

    return {
        "claim_id": claim_id,
        "payer_name": payer_name,
        "payer_id": payer_id,
        "payer": payer_name,
        "npi": header.get("npi", "").strip(),
        "provider_specialty": header.get("provider_specialty", "").strip(),
        "note_text": header.get("note_text", "").strip(),
        "cpt_codes": cpt_codes,
        "icd10_codes": icd10_codes,
        "modifiers": modifiers,
        "place_of_service": "",
        "units": {},
        "service_lines": normalized_lines,
        "description": f"Manual entry — {payer_name}",
    }
