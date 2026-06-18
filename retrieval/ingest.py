"""
LCD/NCD/Article ingestion from the CMS Coverage API (MCD API).

Fetches Local Coverage Determinations (LCDs), National Coverage Determinations
(NCDs), and Coverage Articles (policy articles associated with LCDs that specify
coding guidelines and billing instructions) from the public CMS Coverage API.

Base URL: https://api.coverage.cms.gov. Verified live against real endpoints
(Session 1D, TD-18 resolution — see Technical_Debt_Register.md):
  - GET /v1/data/lcd?lcdid={lcd_id}                — LCD document detail. Requires
        an Authorization: Bearer token (see _get_license_token()).
  - GET /v1/data/ncd?ncdid={ncd_id}                — NCD document detail. No auth
        required.
  - GET /v1/data/article?articleid={article_id}    — Article document detail.
        Requires a Bearer token.
  - GET /v1/metadata/license-agreement             — issues a Bearer token (valid
        ~1 hour) just by being called; no request body or explicit "accept" step.

Every data endpoint wraps its payload as {"meta": {...}, "data": [{...}]} — a
single-element list, even for a single-document lookup. _extract_record() unwraps
this; normalize_lcd/_ncd/_article() operate on the unwrapped record dict.

Output contract: each fetched document is normalized into the raw-document
shape consumed by retrieval/chunking.py:chunk_document() —
    {
        "document_id": str,
        "document_title": str,
        "document_type": "LCD" | "NCD" | "Article",
        "contractor": str | None,
        "effective_date": str | None,
        "sections": [{"heading": str, "text": str}, ...],
    }
— and saved as raw JSON to data/reference/coverage/{document_type}_{document_id}.json
for versioning and offline re-use. data/reference/coverage/ is gitignored;
re-running ingestion is the source of truth, not the committed repo.

Known limitation: contractor is NOT a field on the LCD/Article record itself —
CMS exposes it via a separate sub-resource endpoint (e.g.
/v1/data/lcd/contractor?lcdid={id}&ver={version}, confirmed live) that returns
a contractor_id, not a name, requiring a further lookup against a contractor
reference table. That second hop is out of scope for this sprint; `contractor`
is left as None for LCD and Article. NCD is correctly None always (NCDs are
national, no contractor).

Date format note: CMS returns dates as "MM/DD/YYYY" strings (e.g. "04/01/2023"),
not ISO-8601. effective_date is passed through as-is; no format conversion is
done here. Citation.effective_date is a free-form Optional[str], so this does
not break citation construction, but callers should not assume ISO-8601 sort order.

HTML cleanup: CMS text fields are HTML-entity-encoded HTML fragments (e.g.
"&lt;p&gt;..."). _clean_html() unescapes entities and strips tags so chunked
text is readable prose rather than encoded markup.

Caching: if a document's JSON file already exists locally, fetch_* functions
return the cached copy without making a network call, unless force_refresh=True.

Retry/backoff: transient errors (HTTP 429, connection errors, timeouts) are
retried up to MAX_RETRIES times with exponential backoff before raising.

Refresh cadence: on-demand, run via scripts/ingest_coverage.py.
"""

from __future__ import annotations

import html
import json
import pathlib
import re
import time

import requests

BASE_URL = "https://api.coverage.cms.gov"
DEFAULT_OUTPUT_DIR = pathlib.Path(__file__).parent.parent / "data" / "reference" / "coverage"

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
TIMEOUT_SECONDS = 10
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_token_cache: dict[str, str | None] = {"token": None}


class CoverageAPIError(Exception):
    """Raised when the CMS Coverage API returns a non-retryable error or exhausts retries."""


def _get(url: str, params: dict | None = None, headers: dict | None = None,
         session: requests.Session | None = None) -> dict:
    """GET a URL with retry/backoff on transient errors. Raises CoverageAPIError on failure."""
    client = session or requests
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.get(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_error = exc
        else:
            if response.status_code == 200:
                return response.json()
            if response.status_code not in RETRYABLE_STATUS_CODES:
                raise CoverageAPIError(
                    f"CMS Coverage API request to {url} failed with status {response.status_code}: {response.text[:200]}"
                )
            last_error = CoverageAPIError(f"Retryable status {response.status_code} from {url}")

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt))

    raise CoverageAPIError(f"CMS Coverage API request to {url} failed after {MAX_RETRIES} attempts: {last_error}")


def _extract_record(envelope: dict) -> dict:
    """Unwrap the CMS Coverage API's {"meta": ..., "data": [...]} envelope."""
    data = envelope.get("data")
    if not data:
        return {}
    return data[0]


def _get_license_token(session: requests.Session | None = None) -> str:
    """
    Obtain a Bearer token for the LCD and Article endpoints.

    Calling /v1/metadata/license-agreement issues a token immediately (valid
    ~1 hour) — no separate "accept" request is required. Cached for the
    lifetime of the process; not refreshed on expiry within a single run.
    """
    if _token_cache["token"] is None:
        envelope = _get(f"{BASE_URL}/v1/metadata/license-agreement", session=session)
        record = _extract_record(envelope)
        _token_cache["token"] = record.get("Token")
    return _token_cache["token"]


def _clean_html(text: str | None) -> str | None:
    """
    Unescape HTML entities and strip tags from a CMS text field.

    CMS text fields are double HTML-entity-encoded (e.g. "&amp;ldquo;" decodes
    to "&ldquo;" on one pass, "“" only after a second pass) — confirmed
    live against a real LCD response. html.unescape() is applied repeatedly
    until the text stops changing, bounded at 3 passes.
    """
    if not text:
        return text
    unescaped = text
    for _ in range(3):
        next_pass = html.unescape(unescaped)
        if next_pass == unescaped:
            break
        unescaped = next_pass
    stripped = re.sub(r"<[^>]+>", "", unescaped)
    return re.sub(r"\s+", " ", stripped).strip()


def _cache_path(document_type: str, document_id: str, output_dir: pathlib.Path) -> pathlib.Path:
    return output_dir / f"{document_type}_{document_id}.json"


def _load_cached(document_type: str, document_id: str, output_dir: pathlib.Path) -> dict | None:
    path = _cache_path(document_type, document_id, output_dir)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_document(document: dict, output_dir: pathlib.Path = DEFAULT_OUTPUT_DIR) -> pathlib.Path:
    """Save a normalized document record to data/reference/coverage/ as raw JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(document["document_type"], document["document_id"], output_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2)
    return path


def _first_present(record: dict, *keys, default=None):
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return default


def normalize_lcd(record: dict) -> dict:
    """Normalize an unwrapped CMS LCD record into the chunking.py document contract."""
    return {
        "document_id": str(_first_present(record, "lcd_id", default="")),
        "document_title": _clean_html(_first_present(record, "title", default="")),
        "document_type": "LCD",
        "contractor": None,  # not a field on the LCD record — see module docstring
        "effective_date": _first_present(record, "rev_eff_date", "orig_det_eff_date", default=None),
        "sections": _extract_sections(record, _LCD_SECTION_FIELDS),
    }


def normalize_ncd(record: dict) -> dict:
    """Normalize an unwrapped CMS NCD record into the chunking.py document contract."""
    return {
        "document_id": str(_first_present(record, "document_id", default="")),
        "document_title": _clean_html(_first_present(record, "title", default="")),
        "document_type": "NCD",
        "contractor": None,  # NCDs are national — no contractor
        "effective_date": _first_present(record, "effective_date", "implementation_date", default=None),
        "sections": _extract_sections(record, _NCD_SECTION_FIELDS),
    }


def normalize_article(record: dict) -> dict:
    """Normalize an unwrapped CMS Article record into the chunking.py document contract."""
    return {
        "document_id": str(_first_present(record, "article_id", default="")),
        "document_title": _clean_html(_first_present(record, "title", default="")),
        "document_type": "Article",
        "contractor": None,  # not a field on the Article record — see module docstring
        "effective_date": _first_present(record, "article_eff_date", default=None),
        "sections": _extract_sections(record, _ARTICLE_SECTION_FIELDS),
    }


# Field name -> human-readable section heading, verified live against real
# CMS Coverage API responses (Session 1D). Order is display order.
_LCD_SECTION_FIELDS = [
    ("indication", "Coverage Indications, Limitations, and/or Medical Necessity"),
    ("diagnoses_support", "Covered ICD-10 Codes"),
    ("diagnoses_dont_support", "Non-Covered ICD-10 Codes"),
    ("coding_guidelines", "Coding Guidelines"),
    ("doc_reqs", "Documentation Requirements"),
    ("bibliography", "Bibliography"),
]

_NCD_SECTION_FIELDS = [
    ("item_service_description", "Item/Service Description"),
    ("indications_limitations", "Indications and Limitations of Coverage"),
    ("other_text", "Other"),
    ("ama_statement", "AMA Statement"),
    ("reasons_for_denial", "Reasons for Denial"),
]

_ARTICLE_SECTION_FIELDS = [
    ("description", "Description"),
    ("icd9_covered_para", "Covered Diagnoses"),
    ("icd9_noncovered_para", "Non-Covered Diagnoses"),
    ("other_comments", "Other Comments"),
]


def _extract_sections(record: dict, section_fields: list[tuple[str, str]]) -> list[dict]:
    """Pull known section fields out of an unwrapped record into cleaned {heading, text} dicts."""
    sections = []
    for field_name, heading in section_fields:
        text = _clean_html(record.get(field_name))
        if text:
            sections.append({"heading": heading, "text": text})
    return sections


def fetch_lcd(lcd_id: str, output_dir: pathlib.Path = DEFAULT_OUTPUT_DIR, force_refresh: bool = False,
              session: requests.Session | None = None) -> dict:
    """Fetch an LCD by ID, using the local cache unless force_refresh=True."""
    if not force_refresh:
        cached = _load_cached("LCD", lcd_id, output_dir)
        if cached is not None:
            return cached

    token = _get_license_token(session=session)
    envelope = _get(f"{BASE_URL}/v1/data/lcd", params={"lcdid": lcd_id},
                     headers={"Authorization": f"Bearer {token}"}, session=session)
    document = normalize_lcd(_extract_record(envelope))
    save_document(document, output_dir)
    return document


def fetch_ncd(ncd_id: str, output_dir: pathlib.Path = DEFAULT_OUTPUT_DIR, force_refresh: bool = False,
              session: requests.Session | None = None) -> dict:
    """Fetch an NCD by ID, using the local cache unless force_refresh=True."""
    if not force_refresh:
        cached = _load_cached("NCD", ncd_id, output_dir)
        if cached is not None:
            return cached

    envelope = _get(f"{BASE_URL}/v1/data/ncd", params={"ncdid": ncd_id}, session=session)
    document = normalize_ncd(_extract_record(envelope))
    save_document(document, output_dir)
    return document


def fetch_article(article_id: str, output_dir: pathlib.Path = DEFAULT_OUTPUT_DIR, force_refresh: bool = False,
                   session: requests.Session | None = None) -> dict:
    """Fetch a Coverage Article by ID, using the local cache unless force_refresh=True."""
    if not force_refresh:
        cached = _load_cached("Article", article_id, output_dir)
        if cached is not None:
            return cached

    token = _get_license_token(session=session)
    envelope = _get(f"{BASE_URL}/v1/data/article", params={"articleid": article_id},
                     headers={"Authorization": f"Bearer {token}"}, session=session)
    document = normalize_article(_extract_record(envelope))
    save_document(document, output_dir)
    return document
