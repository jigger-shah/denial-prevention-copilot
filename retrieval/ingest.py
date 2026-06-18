"""
LCD/NCD/Article ingestion from the CMS Coverage API (MCD API).

Fetches Local Coverage Determinations (LCDs), National Coverage Determinations
(NCDs), and Coverage Articles (policy articles associated with LCDs that specify
coding guidelines and billing instructions) from the public CMS Coverage API.

Base URL: https://api.coverage.cms.gov (no API key required as of Feb 2024).
Endpoints used:
  - GET /v1/data/lcd/{lcd_id}      — LCD document detail
  - GET /v1/reports/national-coverage-ncd/{ncd_id} — NCD document detail
  - GET /v1/data/article/{article_id} — Article document detail

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

Caching: if a document's JSON file already exists locally, fetch_* functions
return the cached copy without making a network call, unless force_refresh=True.

Retry/backoff: transient errors (HTTP 429, connection errors, timeouts) are
retried up to MAX_RETRIES times with exponential backoff before raising.

Field-name note: the CMS Coverage API's exact response schema could not be
verified against a live call in this development environment (outbound network
access to api.coverage.cms.gov is restricted here). normalize_lcd/_ncd/_article()
below check multiple plausible field-name candidates (documented inline) and
default missing fields to None/"" rather than raising, so ingestion degrades
gracefully if a real response differs from what's assumed. This should be
verified against a live response before this pipeline is relied upon for a
real demo — see Technical_Debt_Register.md.

Refresh cadence: on-demand, run via scripts/ingest_coverage.py.
"""

from __future__ import annotations

import json
import pathlib
import time

import requests

BASE_URL = "https://api.coverage.cms.gov"
DEFAULT_OUTPUT_DIR = pathlib.Path(__file__).parent.parent / "data" / "reference" / "coverage"

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
TIMEOUT_SECONDS = 10
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class CoverageAPIError(Exception):
    """Raised when the CMS Coverage API returns a non-retryable error or exhausts retries."""


def _get(url: str, params: dict | None = None, session: requests.Session | None = None) -> dict:
    """GET a URL with retry/backoff on transient errors. Raises CoverageAPIError on failure."""
    client = session or requests
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.get(url, params=params, timeout=TIMEOUT_SECONDS)
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


def _first_present(raw: dict, *keys, default=None):
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return default


def normalize_lcd(raw: dict) -> dict:
    """Normalize a raw CMS LCD API response into the chunking.py document contract."""
    return {
        "document_id": str(_first_present(raw, "lcd_id", "document_id", "id", default="")),
        "document_title": _first_present(raw, "title", "document_title", default=""),
        "document_type": "LCD",
        "contractor": _first_present(raw, "contractor_name", "contractor", default=None),
        "effective_date": _first_present(raw, "original_effective_date", "effective_date", default=None),
        "sections": _extract_sections(raw),
    }


def normalize_ncd(raw: dict) -> dict:
    """Normalize a raw CMS NCD API response into the chunking.py document contract."""
    return {
        "document_id": str(_first_present(raw, "ncd_id", "document_id", "id", default="")),
        "document_title": _first_present(raw, "title", "document_title", default=""),
        "document_type": "NCD",
        "contractor": None,  # NCDs are national — no contractor
        "effective_date": _first_present(raw, "effective_date", "implementation_date", default=None),
        "sections": _extract_sections(raw),
    }


def normalize_article(raw: dict) -> dict:
    """Normalize a raw CMS Coverage Article API response into the chunking.py document contract."""
    return {
        "document_id": str(_first_present(raw, "article_id", "document_id", "id", default="")),
        "document_title": _first_present(raw, "title", "document_title", default=""),
        "document_type": "Article",
        "contractor": _first_present(raw, "contractor_name", "contractor", default=None),
        "effective_date": _first_present(raw, "original_effective_date", "effective_date", default=None),
        "sections": _extract_sections(raw),
    }


# Known LCD/NCD/Article section field names, in display order. The CMS API
# represents each policy section as a separate top-level field rather than a
# nested list; this maps the plausible field names to a human-readable heading.
_SECTION_FIELD_HEADINGS = [
    ("indication_limitation", "Indications and Limitations of Coverage"),
    ("indications_limitations", "Indications and Limitations of Coverage"),
    ("coverage_indications", "Coverage Indications, Limitations, and/or Medical Necessity"),
    ("documentation_requirements", "Documentation Requirements"),
    ("documentation_requirement", "Documentation Requirements"),
    ("covered_codes", "Covered ICD-10 Codes"),
    ("noncovered_codes", "Non-Covered ICD-10 Codes"),
    ("bibliography", "Bibliography"),
]


def _extract_sections(raw: dict) -> list[dict]:
    """Pull known section fields out of a raw API response into {heading, text} dicts."""
    sections = []
    for field_name, heading in _SECTION_FIELD_HEADINGS:
        text = raw.get(field_name)
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

    raw = _get(f"{BASE_URL}/v1/data/lcd/{lcd_id}", session=session)
    document = normalize_lcd(raw)
    save_document(document, output_dir)
    return document


def fetch_ncd(ncd_id: str, output_dir: pathlib.Path = DEFAULT_OUTPUT_DIR, force_refresh: bool = False,
              session: requests.Session | None = None) -> dict:
    """Fetch an NCD by ID, using the local cache unless force_refresh=True."""
    if not force_refresh:
        cached = _load_cached("NCD", ncd_id, output_dir)
        if cached is not None:
            return cached

    raw = _get(f"{BASE_URL}/v1/reports/national-coverage-ncd/{ncd_id}", session=session)
    document = normalize_ncd(raw)
    save_document(document, output_dir)
    return document


def fetch_article(article_id: str, output_dir: pathlib.Path = DEFAULT_OUTPUT_DIR, force_refresh: bool = False,
                   session: requests.Session | None = None) -> dict:
    """Fetch a Coverage Article by ID, using the local cache unless force_refresh=True."""
    if not force_refresh:
        cached = _load_cached("Article", article_id, output_dir)
        if cached is not None:
            return cached

    raw = _get(f"{BASE_URL}/v1/data/article/{article_id}", session=session)
    document = normalize_article(raw)
    save_document(document, output_dir)
    return document
