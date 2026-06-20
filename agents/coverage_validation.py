"""
Coverage Validation Agent — v2 (ChromaDB vector retrieval, JSON fallback).

Retrieves up to 3 LCD/NCD/Article policy chunks for the claim's CPT and
ICD-10 codes, then asks Claude (via structured tool use) to evaluate coverage
and medical necessity.

Retrieval order (see _retrieve_policies()):
  1. Query the ChromaDB vector store (retrieval/vector_store.py) built from
     real CMS ingestion (retrieval/ingest.py + retrieval/chunking.py).
  2. If the vector store is empty, returns no results, or raises — fall back
     to the curated JSON policy corpus (retrieval/policy_repository.py).
  3. If both are empty — no retrieval, no model call, return [].

This fallback exists because the ChromaDB index must be explicitly seeded via
scripts/ingest_coverage.py before it has anything to query; until then (or if
ingestion/embedding fails at demo time), the JSON corpus keeps the existing
demo scenarios working exactly as before. Both retrieval paths are converted
into the same policy-dict shape before reaching _build_user_message() and
_parse_response() — neither of those functions, nor the tool schema, citation
grounding, or audit workflow downstream, changed in this swap.

Governance rules (all enforced here):
  - No API key → return []
  - No retrieved LCD/NCD/Article policy (from either source) → return []
  - One model call per invocation, no background calls
  - Model must call a tool (tool_choice="any"); otherwise return []
  - citation_doc_id not in retrieved set → suppress finding
  - Model raises exception → return []
"""

import hashlib
import logging
import os
import pathlib
import re

import anthropic
from dotenv import load_dotenv

from retrieval.chunking import (
    is_low_information_excerpt,
    starts_with_dangling_fragment,
    trim_leading_fragment,
)
from retrieval.policy_repository import find_policies_by_codes
from retrieval.vector_store import VectorStore
from rules.models import Citation, ClaimIn, Finding

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-6"
_LCD_SOURCE_TYPES = {"LCD", "NCD"}
_MAX_POLICIES = 3
_EXCERPT_SNIPPET_MAX_CHARS = 400
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s")
_CHROMA_DIR = pathlib.Path(__file__).parent.parent / "retrieval" / "chroma_db"

_vector_store_instance: VectorStore | None = None

_SYSTEM_PROMPT = (
    "You are a medical billing compliance specialist reviewing a healthcare claim "
    "for potential coverage and medical necessity issues before submission.\n\n"
    "You will be given a claim summary and relevant Local Coverage Determinations (LCDs) "
    "or National Coverage Determinations (NCDs). Your task is to identify whether the "
    "claim has a coverage or medical necessity concern based solely on the provided policy text.\n\n"
    "The claim summary lists any deterministic rule-layer findings already identified for this "
    "claim (NCCI bundling edits, MUE unit limits, modifier requirements, ICD-10/CPT code validity, "
    "diagnosis-procedure conflicts), or the word \"none\" if the rule layer found nothing.\n\n"
    "If that list is \"none\": evaluate the claim normally, based solely on the provided policy "
    "text, exactly as if no other check had run. The absence of a rule-layer finding is not "
    "evidence that the claim is clean — do not become more conservative or default toward "
    "no_coverage_concern just because the list is empty. Report a genuine, policy-supported "
    "coverage or medical-necessity concern whenever you find one.\n\n"
    "If that list is non-empty: Do not restate or duplicate those findings — they are handled by a "
    "separate rule engine, not by you. In this case only, apply a stricter standard: call "
    "report_coverage_finding only if the policy text reveals a medical-necessity concern that is "
    "genuinely distinct from those findings, independently supported by the cited text, and "
    "material to denial risk — not a generic restatement of the same code combination or a vague "
    "payer-scrutiny caveat. If the rule-layer findings already explain the claim's risk and the "
    "policy text adds nothing distinct, call no_coverage_concern.\n\n"
    "Rules:\n"
    "- Only cite a policy document that was provided to you in this message.\n"
    "- Do not invent, guess, or recall policy text from training data.\n"
    "- If the provided policies clearly support coverage, call no_coverage_concern.\n"
    "- If you identify a coverage or medical necessity concern supported by the policy text, "
    "call report_coverage_finding with a specific citation from the provided documents.\n"
    "- Do not call report_coverage_finding for a generic payer-scrutiny caution that is not tied to a "
    "specific, cited policy concern.\n"
    "- You must call exactly one tool."
)

_TOOLS = [
    {
        "name": "report_coverage_finding",
        "description": (
            "Report a coverage or medical necessity concern identified in the claim. "
            "Only call this tool if you found a specific concern supported by the provided policy text. "
            "You must cite a document_id from the policies provided in this message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue": {
                    "type": "string",
                    "description": "Short description of the coverage or medical necessity concern.",
                },
                "recommendation": {
                    "type": "string",
                    "description": "What the billing specialist should do to resolve or document this concern.",
                },
                "severity": {
                    "type": "string",
                    "enum": ["HIGH", "MEDIUM", "LOW"],
                    "description": "HIGH = likely denial, MEDIUM = documentation gap, LOW = advisory.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score 0.0–1.0 that this is a real coverage concern.",
                },
                "citation_doc_id": {
                    "type": "string",
                    "description": "document_id of the policy document being cited (must be from the provided list).",
                },
                "citation_section": {
                    "type": "string",
                    "description": "Section name or heading within the cited document.",
                },
                "citation_excerpt": {
                    "type": "string",
                    "description": "Verbatim excerpt from the cited document that supports this finding.",
                },
            },
            "required": [
                "issue",
                "recommendation",
                "severity",
                "confidence",
                "citation_doc_id",
                "citation_section",
                "citation_excerpt",
            ],
        },
    },
    {
        "name": "no_coverage_concern",
        "description": (
            "Call this tool when the provided policies support coverage and you have "
            "no coverage or medical necessity concern to report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why no concern was found.",
                },
            },
            "required": ["reason"],
        },
    },
]


def validate_coverage(
    claim: ClaimIn, rule_findings: list[Finding] | None = None
) -> tuple[list[Finding], list[dict]]:
    """
    Run coverage validation for a claim. Returns (findings, retrieved_policies):
      - findings: 0 or 1 Finding in practice — one model call, one tool call.
      - retrieved_policies: up to 3 policy dicts considered for this claim
        (document_id, title, section, effective_date, edition, excerpt), so the
        UI can show "Supporting Policies Reviewed" — other policies considered
        but not the basis for the finding (TD-22). This is the same retrieval
        already done internally; no new retrieval or model call.

    rule_findings (optional, TD-24 Phase 3): the rule-layer findings already
    identified for this claim, if any. Passed through to the model so it can
    avoid restating or piling on top of a deterministic finding the rule
    engine already raised — see _SYSTEM_PROMPT. Omitting it (the default)
    preserves prior behavior exactly.

    findings is [] if no API key, no matching LCD/NCD policies, model error, or
    model calls no_coverage_concern.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return [], []

    lcd_policies = _retrieve_policies(claim)
    if not lcd_policies:
        return [], []

    retrieved_doc_ids = {p["document_id"] for p in lcd_policies}

    model = os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL)
    user_message = _build_user_message(claim, lcd_policies, rule_findings)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=_TOOLS,
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        logger.warning("Coverage validation API error: %s", exc)
        return [], lcd_policies

    findings = _parse_response(response, retrieved_doc_ids, lcd_policies, claim.claim_id)
    return findings, lcd_policies


def _get_vector_store() -> VectorStore:
    """Lazily construct the single process-lifetime VectorStore against retrieval/chroma_db/."""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStore(persist_directory=_CHROMA_DIR)
    return _vector_store_instance


def _build_retrieval_query(claim: ClaimIn) -> str:
    """Build a semantic query from the claim's CPT/HCPCS and ICD-10 codes."""
    parts = []
    if claim.cpt_codes:
        parts.append("CPT codes: " + ", ".join(claim.cpt_codes))
    if claim.icd10_codes:
        parts.append("ICD-10 codes: " + ", ".join(claim.icd10_codes))
    return ". ".join(parts)


def _vector_result_to_policy(result: dict) -> dict:
    """Convert a vector_store.query() chunk result into the policy-dict shape _build_user_message() expects."""
    return {
        "document_id": result.get("document_id", ""),
        "title": result.get("document_title", ""),
        "section": result.get("section_heading", ""),
        "effective_date": result.get("effective_date"),
        "edition": "",
        "excerpt": result.get("text", ""),
    }


def _retrieve_from_vector_store(claim: ClaimIn) -> list[dict]:
    """
    Query the ChromaDB vector store. Returns [] (never raises) if the query
    text is empty, the store is empty, or the store raises for any reason —
    all of these defer to the JSON fallback in _retrieve_policies().
    """
    query_text = _build_retrieval_query(claim)
    if not query_text:
        return []

    try:
        store = _get_vector_store()
        if store.count() == 0:
            return []
        results = store.query(query_text, n_results=_MAX_POLICIES)
    except Exception as exc:
        logger.warning("Vector store retrieval failed, falling back to JSON policy corpus: %s", exc)
        return []

    return [_vector_result_to_policy(r) for r in results[:_MAX_POLICIES]]


def _retrieve_from_json_fallback(claim: ClaimIn) -> list[dict]:
    """Curated JSON policy corpus — the only retrieval path before this sprint."""
    all_policies = find_policies_by_codes(
        cpt_codes=claim.cpt_codes,
        icd10_codes=claim.icd10_codes,
    )
    lcd_policies = [p for p in all_policies if p.get("source_type") in _LCD_SOURCE_TYPES]
    return lcd_policies[:_MAX_POLICIES]


def _retrieve_policies(claim: ClaimIn) -> list[dict]:
    """Vector store first; JSON policy corpus if the vector store has nothing usable."""
    vector_policies = _retrieve_from_vector_store(claim)
    if vector_policies:
        return vector_policies
    return _retrieve_from_json_fallback(claim)


def _sentence_snippet(text: str, max_chars: int = _EXCERPT_SNIPPET_MAX_CHARS) -> str:
    """
    Trim a retrieved policy's chunk text to a clean, sentence-bounded snippet
    suitable for display as a citation excerpt — used as the fallback when the
    model's own citation_excerpt looks like a fragment (see _clean_citation_excerpt).
    """
    cleaned = trim_leading_fragment(text.strip())
    if len(cleaned) <= max_chars:
        return cleaned

    truncated = cleaned[:max_chars]
    last_boundary = None
    for match in _SENTENCE_BOUNDARY.finditer(truncated):
        last_boundary = match.start()
    if last_boundary:
        return truncated[:last_boundary + 1].strip()
    return truncated.rstrip() + "…"


def _clean_citation_excerpt(model_excerpt: str, fallback_chunk_text: str) -> str:
    """
    Use the model's citation_excerpt if it reads as clean, complete,
    substantive text.

    Falls back to a cleaned, sentence-bounded snippet of the actual retrieved
    policy text it was grounded in — never raw, unfiltered model output — when
    the model's excerpt is empty, starts with dangling closing punctuation/
    quotes (a sign of a mid-sentence chunk boundary), or is low-information
    boilerplate (grammatically complete but navigational, e.g. "Scroll down
    for links..." — see TD-26). Never an empty excerpt when a retrieved chunk
    is available.
    """
    candidate = (model_excerpt or "").strip()
    if (
        candidate
        and not starts_with_dangling_fragment(candidate)
        and not is_low_information_excerpt(candidate)
    ):
        return candidate
    if fallback_chunk_text:
        return _sentence_snippet(fallback_chunk_text)
    return candidate


def _summarize_rule_findings(rule_findings: list[Finding] | None) -> str:
    """Comma-joined, de-duplicated rule names already raised by the rule layer, or 'none'."""
    if not rule_findings:
        return "none"
    return ", ".join(dict.fromkeys(f.rule for f in rule_findings))


def _build_user_message(
    claim: ClaimIn, lcd_policies: list[dict], rule_findings: list[Finding] | None = None
) -> str:
    cpt = ", ".join(claim.cpt_codes) if claim.cpt_codes else "none"
    icd = ", ".join(claim.icd10_codes) if claim.icd10_codes else "none"
    mods = ", ".join(claim.modifiers) if claim.modifiers else "none"
    rule_summary = _summarize_rule_findings(rule_findings)

    policy_blocks = []
    for p in lcd_policies:
        policy_blocks.append(
            f"--- POLICY DOCUMENT ---\n"
            f"document_id: {p['document_id']}\n"
            f"title: {p['title']}\n"
            f"section: {p['section']}\n"
            f"effective_date: {p.get('effective_date', 'N/A')}\n"
            f"excerpt:\n{p['excerpt']}"
        )

    return (
        f"CLAIM SUMMARY\n"
        f"Claim ID: {claim.claim_id}\n"
        f"CPT codes: {cpt}\n"
        f"ICD-10 codes: {icd}\n"
        f"Modifiers: {mods}\n"
        f"Place of service: {claim.place_of_service}\n"
        f"Payer: {claim.payer}\n"
        f"Rule-layer findings already identified for this claim: {rule_summary}\n\n"
        f"RELEVANT POLICY DOCUMENTS ({len(lcd_policies)} retrieved)\n\n"
        + "\n\n".join(policy_blocks)
        + "\n\n"
        "Review this claim against the policy documents above. Call report_coverage_finding "
        "only if you identify a coverage or medical necessity concern that is distinct from the "
        "rule-layer findings listed above, independently supported by the cited policy text, and "
        "material to denial risk. Otherwise call no_coverage_concern."
    )


def _parse_response(
    response: object,
    retrieved_doc_ids: set[str],
    lcd_policies: list[dict],
    claim_id: str,
) -> list[Finding]:
    for block in response.content:
        if block.type != "tool_use":
            continue

        if block.name == "no_coverage_concern":
            return []

        if block.name == "report_coverage_finding":
            args = block.input
            doc_id = args.get("citation_doc_id", "")

            # Citation grounding: suppress if doc_id not in what we retrieved
            if doc_id not in retrieved_doc_ids:
                logger.warning(
                    "Coverage agent cited doc_id %r not in retrieved set %r — suppressed",
                    doc_id,
                    retrieved_doc_ids,
                )
                return []

            policy = next((p for p in lcd_policies if p["document_id"] == doc_id), {})
            citation = Citation(
                source="coverage_validation",
                doc_id=doc_id,
                section=args.get("citation_section", policy.get("section", "")),
                edition=policy.get("edition", ""),
                effective_date=policy.get("effective_date"),
                excerpt=_clean_citation_excerpt(args.get("citation_excerpt", ""), policy.get("excerpt", "")),
            )

            severity = args.get("severity", "MEDIUM")
            if severity not in ("HIGH", "MEDIUM", "LOW"):
                severity = "MEDIUM"

            finding = Finding(
                rule="coverage_validation",
                severity=severity,
                issue=args.get("issue", "Coverage concern identified"),
                recommendation=args.get("recommendation", "Review policy and documentation."),
                citation=citation,
                confidence=float(args.get("confidence", 0.7)),
                source="agent_layer",
            )
            finding.finding_id = _stable_finding_id(claim_id, doc_id, finding.issue)
            return [finding]

    # Model produced no tool_use block — no finding
    return []


def _stable_finding_id(claim_id: str, doc_id: str, issue: str) -> str:
    payload = f"{claim_id}|{doc_id}|{issue}"
    return "cov-" + hashlib.sha256(payload.encode()).hexdigest()[:12]
