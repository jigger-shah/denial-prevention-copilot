"""
Tests for agents/coding_validation.py — all model calls are mocked.

No real Anthropic API calls are made. The mock replaces
`agents.coding_validation.anthropic.Anthropic` so the client
is never actually instantiated.

No real ChromaDB index is used either. `mock_vector_store` (autouse) patches
`agents.coding_validation._get_vector_store` with a MagicMock whose
`count()` defaults to 0 — every test in this file therefore exercises the
JSON policy_repository fallback path by default, exactly as in
test_coverage_validation.py, unless a test explicitly configures the mock's
`count`/`query` to simulate vector results.
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.coding_validation import validate_coding, _stable_finding_id
from rules.models import ClaimIn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_vector_store(monkeypatch):
    """Default: empty vector store, so every test falls back to JSON unless it opts in to vector results."""
    store = MagicMock()
    store.count.return_value = 0
    monkeypatch.setattr("agents.coding_validation._get_vector_store", lambda: store)
    return store


def _claim(
    cpt_codes=None,
    icd10_codes=None,
    modifiers=None,
    claim_id="CLM-TEST-001",
):
    return ClaimIn(
        claim_id=claim_id,
        payer="MEDICARE",
        npi="1234567893",
        cpt_codes=cpt_codes or [],
        icd10_codes=icd10_codes or [],
        modifiers=modifiers or [],
        place_of_service="11",
        units={},
        note_text="",
        description="",
    )


def _vector_chunk(document_id, text, section_heading="Indications", document_title="Test Policy",
                   effective_date="2026-01-01", chunk_index=0, distance=0.3):
    return {
        "document_id": document_id,
        "document_title": document_title,
        "section_heading": section_heading,
        "effective_date": effective_date,
        "chunk_index": chunk_index,
        "text": text,
        "distance": distance,
    }


def _tool_use_block(name: str, input_dict: dict):
    block = SimpleNamespace()
    block.type = "tool_use"
    block.name = name
    block.input = input_dict
    return block


def _text_block(text: str = "ok"):
    block = SimpleNamespace()
    block.type = "text"
    block.text = text
    return block


def _mock_response(*blocks):
    response = MagicMock()
    response.content = list(blocks)
    return response


# ---------------------------------------------------------------------------
# Tests: pre-flight guards (no API call needed)
# ---------------------------------------------------------------------------

def test_missing_api_key_returns_empty_no_exception(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = validate_coding(_claim(icd10_codes=["Z00.00"]))
    assert result == []


def test_empty_api_key_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    result = validate_coding(_claim(icd10_codes=["Z00.00"]))
    assert result == []


def test_claim_with_no_lcd_policy_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = validate_coding(_claim(cpt_codes=["ZZZZ99"], icd10_codes=["Q00.0"]))
    assert result == []


# ---------------------------------------------------------------------------
# Tests: model call outcomes
# ---------------------------------------------------------------------------

@patch("agents.coding_validation.anthropic.Anthropic")
def test_valid_report_finding_produces_one_finding(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "Diagnosis lacks specificity to support billed E/M level",
        "recommendation": "Use a more specific ICD-10 code reflecting the documented condition.",
        "severity": "MEDIUM",
        "confidence": 0.85,
        "citation_doc_id": "LCD_E_M_MEDICAL_NECESSITY_Z00",
        "citation_section": "Indications and Limitations of Coverage and/or Medical Necessity",
        "citation_excerpt": "Problem-oriented E/M services billed with Z00.00 require modifier 25.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    assert len(findings) == 1
    f = findings[0]
    assert f.rule == "coding_validation"
    assert f.severity == "MEDIUM"
    assert f.source == "agent_layer"
    assert f.citation.doc_id == "LCD_E_M_MEDICAL_NECESSITY_Z00"
    assert f.confidence == pytest.approx(0.85)


@patch("agents.coding_validation.anthropic.Anthropic")
def test_finding_has_stable_finding_id(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "Coding defensibility concern",
        "recommendation": "Review.",
        "severity": "LOW",
        "confidence": 0.6,
        "citation_doc_id": "LCD_E_M_MEDICAL_NECESSITY_Z00",
        "citation_section": "Section 1",
        "citation_excerpt": "excerpt text",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings1 = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"], claim_id="CLM-STABLE"))
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)
    findings2 = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"], claim_id="CLM-STABLE"))

    assert findings1[0].finding_id == findings2[0].finding_id
    assert findings1[0].finding_id.startswith("cod-")


@patch("agents.coding_validation.anthropic.Anthropic")
def test_no_coding_concern_tool_returns_empty(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("no_coding_concern", {
        "reason": "Diagnosis fully supports billed procedure per LCD.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))
    assert findings == []


@patch("agents.coding_validation.anthropic.Anthropic")
def test_ungrounded_doc_id_suppresses_finding(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "Some concern",
        "recommendation": "Fix it.",
        "severity": "HIGH",
        "confidence": 0.9,
        "citation_doc_id": "INVENTED_DOC_NOT_IN_CORPUS",
        "citation_section": "Section X",
        "citation_excerpt": "hallucinated text",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    # Z00.00 will retrieve LCD_E_M_MEDICAL_NECESSITY_Z00, but the model cites a different doc
    findings = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings == []


@patch("agents.coding_validation.anthropic.Anthropic")
def test_api_exception_returns_empty_no_propagation(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_anthropic.return_value.messages.create.side_effect = RuntimeError("network failure")

    findings = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings == []


@patch("agents.coding_validation.anthropic.Anthropic")
def test_no_tool_use_block_returns_empty(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_anthropic.return_value.messages.create.return_value = _mock_response(
        _text_block("I think there might be an issue but I'm not calling a tool.")
    )

    findings = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings == []


@patch("agents.coding_validation.anthropic.Anthropic")
def test_finding_source_is_coding_validation(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "Specificity issue",
        "recommendation": "Use specific dx code.",
        "severity": "MEDIUM",
        "confidence": 0.75,
        "citation_doc_id": "LCD_E_M_MEDICAL_NECESSITY_Z00",
        "citation_section": "Indications",
        "citation_excerpt": "excerpt",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings[0].citation.source == "coding_validation"


@patch("agents.coding_validation.anthropic.Anthropic")
def test_finding_citation_doc_id_resolves_in_policy_corpus(mock_anthropic, monkeypatch):
    """citation_doc_id on the finding must exist in the policy repository."""
    from retrieval.policy_repository import find_policy_by_document_id

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "Coding defensibility concern",
        "recommendation": "Add documentation.",
        "severity": "LOW",
        "confidence": 0.65,
        "citation_doc_id": "LCD_PREVENTIVE_99395_COVERAGE",
        "citation_section": "Covered Indications and Frequency Limitations",
        "citation_excerpt": "CPT 99395 is covered for established patients.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coding(_claim(cpt_codes=["99395"], icd10_codes=["Z00.00"]))
    assert len(findings) == 1
    doc = find_policy_by_document_id(findings[0].citation.doc_id)
    assert doc is not None


# ---------------------------------------------------------------------------
# Unit test: _stable_finding_id
# ---------------------------------------------------------------------------

def test_stable_finding_id_format():
    fid = _stable_finding_id("CLM-001", "LCD_TEST", "some issue")
    assert fid.startswith("cod-")
    assert len(fid) == 4 + 12  # "cod-" + 12 hex chars


def test_stable_finding_id_is_deterministic():
    a = _stable_finding_id("CLM-001", "LCD_TEST", "issue text")
    b = _stable_finding_id("CLM-001", "LCD_TEST", "issue text")
    assert a == b


def test_stable_finding_id_differs_by_claim():
    a = _stable_finding_id("CLM-001", "LCD_TEST", "issue")
    b = _stable_finding_id("CLM-002", "LCD_TEST", "issue")
    assert a != b


def test_stable_finding_id_differs_from_coverage_agent_for_same_inputs():
    """cod- and cov- prefixes keep coding and coverage finding IDs from colliding even with identical inputs."""
    from agents.coverage_validation import _stable_finding_id as coverage_stable_finding_id

    coding_id = _stable_finding_id("CLM-001", "LCD_TEST", "issue")
    coverage_id = coverage_stable_finding_id("CLM-001", "LCD_TEST", "issue")

    assert coding_id != coverage_id
    assert coding_id.startswith("cod-")
    assert coverage_id.startswith("cov-")


# ---------------------------------------------------------------------------
# Vector retrieval + JSON fallback (mirrors test_coverage_validation.py)
# ---------------------------------------------------------------------------

@patch("agents.coding_validation.anthropic.Anthropic")
def test_vector_store_queried_when_it_has_results(mock_anthropic, mock_vector_store, monkeypatch):
    """When the vector store has chunks, query() is called and its results are used (not the JSON corpus)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 5
    mock_vector_store.query.return_value = [
        _vector_chunk("LCD_VECTOR_001", "Coding requires a specific diagnosis.")
    ]

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "Diagnosis specificity concern",
        "recommendation": "Use a more specific diagnosis code.",
        "severity": "MEDIUM",
        "confidence": 0.8,
        "citation_doc_id": "LCD_VECTOR_001",
        "citation_section": "Indications",
        "citation_excerpt": "Coding requires a specific diagnosis.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    mock_vector_store.query.assert_called_once()
    assert len(findings) == 1
    assert findings[0].citation.doc_id == "LCD_VECTOR_001"


def test_vector_results_convert_to_policy_like_objects(mock_vector_store):
    """_vector_result_to_policy() maps chunk fields onto the keys _build_user_message() reads."""
    from agents.coding_validation import _vector_result_to_policy

    chunk = _vector_chunk(
        "LCD_VECTOR_002", "Some excerpt text.",
        section_heading="Documentation Requirements",
        document_title="LCD L12345 — Test Policy",
        effective_date="2025-07-01",
    )
    policy = _vector_result_to_policy(chunk)

    assert policy == {
        "document_id": "LCD_VECTOR_002",
        "title": "LCD L12345 — Test Policy",
        "section": "Documentation Requirements",
        "effective_date": "2025-07-01",
        "edition": "",
        "excerpt": "Some excerpt text.",
    }


@patch("agents.coding_validation.anthropic.Anthropic")
def test_citation_grounding_works_with_vector_result_document_id(mock_anthropic, mock_vector_store, monkeypatch):
    """Citation grounding (doc_id must be in the retrieved set) applies identically to vector-sourced policies."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 2
    mock_vector_store.query.return_value = [_vector_chunk("LCD_VECTOR_003", "Real retrieved text.")]

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "Hallucinated concern",
        "recommendation": "Fix it.",
        "severity": "HIGH",
        "confidence": 0.9,
        "citation_doc_id": "LCD_NOT_RETRIEVED",  # not in the vector result set
        "citation_section": "Section X",
        "citation_excerpt": "hallucinated text",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings == []  # suppressed: ungrounded doc_id, even though the source was the vector store


def test_json_fallback_used_when_vector_store_returns_empty_list(mock_vector_store):
    """vector_store.count() > 0 but query() returns [] (e.g. no chunk relevant to this claim) -> JSON fallback."""
    from agents.coding_validation import _retrieve_policies

    mock_vector_store.count.return_value = 5
    mock_vector_store.query.return_value = []

    policies = _retrieve_policies(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    mock_vector_store.query.assert_called_once()
    assert policies  # JSON corpus has a match for Z00.00
    assert all(p["document_id"] != "" for p in policies)


def test_json_fallback_used_when_vector_store_count_is_zero(mock_vector_store):
    """Default fixture state: count()==0 short-circuits before query() is even called."""
    from agents.coding_validation import _retrieve_policies

    policies = _retrieve_policies(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    mock_vector_store.query.assert_not_called()
    assert policies  # JSON corpus has a match for Z00.00


def test_json_fallback_used_when_vector_store_raises(mock_vector_store):
    """vector_store.query() raising (e.g. ChromaDB unavailable) falls back to JSON, never propagates."""
    from agents.coding_validation import _retrieve_policies

    mock_vector_store.count.return_value = 5
    mock_vector_store.query.side_effect = RuntimeError("ChromaDB connection lost")

    policies = _retrieve_policies(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    assert policies  # JSON corpus has a match for Z00.00


def test_no_policy_from_vector_or_json_returns_empty_list(mock_vector_store):
    """Neither source has anything for these codes -> []."""
    from agents.coding_validation import _retrieve_policies

    mock_vector_store.count.return_value = 5
    mock_vector_store.query.return_value = []

    policies = _retrieve_policies(_claim(cpt_codes=["ZZZZ99"], icd10_codes=["Q00.0"]))
    assert policies == []


def test_validate_coding_returns_empty_when_neither_source_has_policies(monkeypatch, mock_vector_store):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 5
    mock_vector_store.query.return_value = []

    findings = validate_coding(_claim(cpt_codes=["ZZZZ99"], icd10_codes=["Q00.0"]))
    assert findings == []


def test_vector_store_not_queried_when_claim_has_no_codes(mock_vector_store, monkeypatch):
    """Empty query text short-circuits before touching the vector store at all."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from agents.coding_validation import _retrieve_from_vector_store

    result = _retrieve_from_vector_store(_claim())
    mock_vector_store.count.assert_not_called()
    assert result == []


@patch("agents.coding_validation.anthropic.Anthropic")
def test_existing_mocked_anthropic_flow_unaffected_by_vector_swap(mock_anthropic, monkeypatch, mock_vector_store):
    """Sanity check: with the vector store empty (default), JSON-fallback behavior is bit-for-bit preserved."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "Diagnosis specificity concern",
        "recommendation": "Use a more specific diagnosis code.",
        "severity": "MEDIUM",
        "confidence": 0.85,
        "citation_doc_id": "LCD_E_M_MEDICAL_NECESSITY_Z00",
        "citation_section": "Indications and Limitations of Coverage and/or Medical Necessity",
        "citation_excerpt": "Problem-oriented E/M services billed with Z00.00 require modifier 25.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coding(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    assert len(findings) == 1
    assert findings[0].citation.doc_id == "LCD_E_M_MEDICAL_NECESSITY_Z00"


# ---------------------------------------------------------------------------
# Excerpt-quality fix: dangling-fragment cleanup and fallback to chunk text
# (mirrors test_coverage_validation.py)
# ---------------------------------------------------------------------------

def test_clean_citation_excerpt_keeps_clean_model_excerpt_unchanged():
    from agents.coding_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt(
        "Problem-oriented E/M services billed with Z00.00 require modifier 25.",
        fallback_chunk_text="irrelevant fallback text.",
    )
    assert result == "Problem-oriented E/M services billed with Z00.00 require modifier 25."


def test_clean_citation_excerpt_falls_back_when_model_excerpt_starts_with_dangling_paren():
    from agents.coding_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt(
        "). This NCD lists the ICD-10 codes for HbA1c for frequencies up to once every 3 months.",
        fallback_chunk_text="HbA1c testing requires a diagnosis code reflecting glycemic control status.",
    )
    assert result == "HbA1c testing requires a diagnosis code reflecting glycemic control status."
    assert not result.startswith(")")


def test_clean_citation_excerpt_falls_back_when_model_excerpt_is_empty():
    from agents.coding_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt("", fallback_chunk_text="Clean fallback sentence.")
    assert result == "Clean fallback sentence."


def test_clean_citation_excerpt_returns_dangling_text_if_no_fallback_available():
    """With no fallback at all, return whatever the model gave rather than an empty string."""
    from agents.coding_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt(") dangling model text.", fallback_chunk_text="")
    assert result == ") dangling model text."


@patch("agents.coding_validation.anthropic.Anthropic")
def test_vector_citation_excerpt_does_not_begin_with_dangling_paren(mock_anthropic, mock_vector_store, monkeypatch):
    """
    Regression test mirroring the coverage-agent production bug fix: the model echoes a
    vector chunk that happened to start right after a closing paren. The finding's
    citation.excerpt must not surface that fragment verbatim.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 1
    mock_vector_store.query.return_value = [_vector_chunk(
        "33431",
        "). This NCD lists the ICD-10 codes for HbA1c for frequencies up to once every 3 months.",
        document_title="HbA1c",
    )]

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "HbA1c diagnosis lacks specificity",
        "recommendation": "Add a more specific diabetes diagnosis code.",
        "severity": "HIGH",
        "confidence": 0.9,
        "citation_doc_id": "33431",
        "citation_section": "Coverage Indications, Limitations, and/or Medical Necessity",
        "citation_excerpt": "). This NCD lists the ICD-10 codes for HbA1c for frequencies up to once every 3 months.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coding(_claim(cpt_codes=["83036"], icd10_codes=["Z00.00"]))

    assert len(findings) == 1
    excerpt = findings[0].citation.excerpt
    assert not excerpt.startswith(")")
    assert not excerpt.startswith(".")
    assert excerpt == "This NCD lists the ICD-10 codes for HbA1c for frequencies up to once every 3 months."


@patch("agents.coding_validation.anthropic.Anthropic")
def test_vector_citation_grounding_still_passes_with_clean_excerpt(mock_anthropic, mock_vector_store, monkeypatch):
    """The excerpt cleanup must not interfere with citation grounding — doc_id matching is unaffected."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 1
    mock_vector_store.query.return_value = [_vector_chunk(
        "33431", "HbA1c testing requires a diagnosis code reflecting glycemic control status.",
        document_title="HbA1c",
    )]

    tool_block = _tool_use_block("report_coding_finding", {
        "issue": "Diagnosis specificity concern",
        "recommendation": "Review diagnosis coding.",
        "severity": "MEDIUM",
        "confidence": 0.8,
        "citation_doc_id": "33431",
        "citation_section": "Coverage Indications, Limitations, and/or Medical Necessity",
        "citation_excerpt": "HbA1c testing requires a diagnosis code reflecting glycemic control status.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coding(_claim(cpt_codes=["83036"], icd10_codes=["Z00.00"]))

    assert len(findings) == 1
    assert findings[0].citation.doc_id == "33431"
    assert findings[0].citation.excerpt == "HbA1c testing requires a diagnosis code reflecting glycemic control status."
