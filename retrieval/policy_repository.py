"""
Policy reference repository — JSON-backed lookup for curated policy examples.

Sprint 3: backed by data/reference/policy_examples.json (curated public-policy-style
references). No vector search, no live CMS API, no Chroma.

Production replacement path:
  Replace _load_policy_references() with a loader that reads from ChromaDB
  (retrieval/vector_store.py) after LCD/NCD documents have been ingested via
  retrieval/ingest.py. The public interface (find_policy_by_document_id,
  find_policies_by_codes, get_citation_detail) stays the same.
"""

import json
import pathlib
from typing import Optional

from rules.models import Citation

_DATA_FILE = pathlib.Path(__file__).parent.parent / "data" / "reference" / "policy_examples.json"

# Module-level cache — loaded once per process.
_cache: Optional[list[dict]] = None


def load_policy_references() -> list[dict]:
    """
    Load and cache all policy references from policy_examples.json.

    Returns a list of policy reference dicts. Each dict has the keys:
      document_id, source_type, title, section, effective_date, edition,
      source_url (optional), excerpt, applies_to_codes, notes.
    """
    global _cache
    if _cache is None:
        with open(_DATA_FILE, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def find_policy_by_document_id(document_id: str) -> Optional[dict]:
    """Return the policy reference matching document_id, or None if not found."""
    for policy in load_policy_references():
        if policy["document_id"] == document_id:
            return policy
    return None


def find_policies_by_codes(
    cpt_codes: list[str] = (),
    icd10_codes: list[str] = (),
    modifiers: list[str] = (),
) -> list[dict]:
    """
    Return all policy references whose applies_to_codes intersects the given codes.

    Matches on CPT codes, ICD-10 codes, and modifier strings (e.g. "25").
    Returns an empty list if no codes are provided or no policies match.
    """
    query_codes = set(cpt_codes) | set(icd10_codes) | set(modifiers)
    if not query_codes:
        return []
    return [
        policy for policy in load_policy_references()
        if query_codes & set(policy.get("applies_to_codes", []))
    ]


def get_citation_detail(citation: Citation) -> Optional[dict]:
    """
    Look up the full policy reference record for a Citation.

    Uses citation.doc_id to find the matching policy entry. Returns the
    full policy dict (including title, source_url, notes) or None if the
    doc_id does not match any loaded policy.

    Used by the UI to enrich the citation detail view beyond what is stored
    directly on the Citation dataclass.
    """
    return find_policy_by_document_id(citation.doc_id)
