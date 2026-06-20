"""
Tests for agents/coverage_validation.py — all model calls are mocked.

No real Anthropic API calls are made. The mock replaces
`agents.coverage_validation.anthropic.Anthropic` so the client
is never actually instantiated.

No real ChromaDB index is used either. `mock_vector_store` (autouse) patches
`agents.coverage_validation._get_vector_store` with a MagicMock whose
`count()` defaults to 0 — every test in this file therefore exercises the
JSON policy_repository fallback path by default, exactly as in v1, unless a
test explicitly configures the mock's `count`/`query` to simulate vector
results (see the "Session 1D" tests below).
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.coverage_validation import (
    _SYSTEM_PROMPT,
    _build_user_message,
    _summarize_rule_findings,
    validate_coverage,
    _stable_finding_id,
)
from rules.models import Citation, ClaimIn, Finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_vector_store(monkeypatch):
    """Default: empty vector store, so every test falls back to JSON unless it opts in to vector results."""
    store = MagicMock()
    store.count.return_value = 0
    monkeypatch.setattr("agents.coverage_validation._get_vector_store", lambda: store)
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
    result = validate_coverage(_claim(icd10_codes=["Z00.00"]))
    assert result == []


def test_empty_api_key_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    result = validate_coverage(_claim(icd10_codes=["Z00.00"]))
    assert result == []


def test_claim_with_no_lcd_policy_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # I10 alone matches LCD_E_M_MEDICAL_NECESSITY_I10; but if we use a code
    # that matches nothing in the corpus we get no policies.
    result = validate_coverage(_claim(cpt_codes=["ZZZZ99"], icd10_codes=["Q00.0"]))
    assert result == []


# ---------------------------------------------------------------------------
# Tests: model call outcomes
# ---------------------------------------------------------------------------

@patch("agents.coverage_validation.anthropic.Anthropic")
def test_valid_report_finding_produces_one_finding(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coverage_finding", {
        "issue": "E/M billed with preventive diagnosis only",
        "recommendation": "Add modifier 25 and a separate problem diagnosis.",
        "severity": "MEDIUM",
        "confidence": 0.85,
        "citation_doc_id": "LCD_E_M_MEDICAL_NECESSITY_Z00",
        "citation_section": "Indications and Limitations of Coverage and/or Medical Necessity",
        "citation_excerpt": "Problem-oriented E/M services billed with Z00.00 require modifier 25.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    assert len(findings) == 1
    f = findings[0]
    assert f.rule == "coverage_validation"
    assert f.severity == "MEDIUM"
    assert f.source == "agent_layer"
    assert f.citation.doc_id == "LCD_E_M_MEDICAL_NECESSITY_Z00"
    assert f.confidence == pytest.approx(0.85)


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_finding_has_stable_finding_id(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coverage_finding", {
        "issue": "Coverage concern",
        "recommendation": "Review.",
        "severity": "LOW",
        "confidence": 0.6,
        "citation_doc_id": "LCD_E_M_MEDICAL_NECESSITY_Z00",
        "citation_section": "Section 1",
        "citation_excerpt": "excerpt text",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings1 = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"], claim_id="CLM-STABLE"))
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)
    findings2 = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"], claim_id="CLM-STABLE"))

    assert findings1[0].finding_id == findings2[0].finding_id
    assert findings1[0].finding_id.startswith("cov-")


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_no_coverage_concern_tool_returns_empty(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("no_coverage_concern", {
        "reason": "Hypertension fully supports E/M service per LCD.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["I10"]))
    assert findings == []


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_ungrounded_doc_id_suppresses_finding(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coverage_finding", {
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
    findings = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings == []


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_api_exception_returns_empty_no_propagation(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_anthropic.return_value.messages.create.side_effect = RuntimeError("network failure")

    findings = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings == []


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_no_tool_use_block_returns_empty(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_anthropic.return_value.messages.create.return_value = _mock_response(
        _text_block("I think there might be an issue but I'm not calling a tool.")
    )

    findings = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings == []


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_finding_source_is_coverage_validation(mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coverage_finding", {
        "issue": "Preventive issue",
        "recommendation": "Add modifier.",
        "severity": "MEDIUM",
        "confidence": 0.75,
        "citation_doc_id": "LCD_E_M_MEDICAL_NECESSITY_Z00",
        "citation_section": "Indications",
        "citation_excerpt": "excerpt",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings[0].citation.source == "coverage_validation"


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_finding_citation_doc_id_resolves_in_policy_corpus(mock_anthropic, monkeypatch):
    """citation_doc_id on the finding must exist in the policy repository."""
    from retrieval.policy_repository import find_policy_by_document_id

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coverage_finding", {
        "issue": "Coverage concern",
        "recommendation": "Add documentation.",
        "severity": "LOW",
        "confidence": 0.65,
        "citation_doc_id": "LCD_PREVENTIVE_99395_COVERAGE",
        "citation_section": "Covered Indications and Frequency Limitations",
        "citation_excerpt": "CPT 99395 is covered for established patients.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coverage(_claim(cpt_codes=["99395"], icd10_codes=["Z00.00"]))
    assert len(findings) == 1
    doc = find_policy_by_document_id(findings[0].citation.doc_id)
    assert doc is not None


# ---------------------------------------------------------------------------
# Unit test: _stable_finding_id
# ---------------------------------------------------------------------------

def test_stable_finding_id_format():
    fid = _stable_finding_id("CLM-001", "LCD_TEST", "some issue")
    assert fid.startswith("cov-")
    assert len(fid) == 4 + 12  # "cov-" + 12 hex chars


def test_stable_finding_id_is_deterministic():
    a = _stable_finding_id("CLM-001", "LCD_TEST", "issue text")
    b = _stable_finding_id("CLM-001", "LCD_TEST", "issue text")
    assert a == b


def test_stable_finding_id_differs_by_claim():
    a = _stable_finding_id("CLM-001", "LCD_TEST", "issue")
    b = _stable_finding_id("CLM-002", "LCD_TEST", "issue")
    assert a != b


# ---------------------------------------------------------------------------
# Session 1D: vector retrieval + JSON fallback
# ---------------------------------------------------------------------------

@patch("agents.coverage_validation.anthropic.Anthropic")
def test_vector_store_queried_when_it_has_results(mock_anthropic, mock_vector_store, monkeypatch):
    """When the vector store has chunks, query() is called and its results are used (not the JSON corpus)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 5
    mock_vector_store.query.return_value = [
        _vector_chunk("LCD_VECTOR_001", "Coverage applies when medically necessary.")
    ]

    tool_block = _tool_use_block("report_coverage_finding", {
        "issue": "Medical necessity concern",
        "recommendation": "Document medical necessity.",
        "severity": "MEDIUM",
        "confidence": 0.8,
        "citation_doc_id": "LCD_VECTOR_001",
        "citation_section": "Indications",
        "citation_excerpt": "Coverage applies when medically necessary.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    mock_vector_store.query.assert_called_once()
    assert len(findings) == 1
    assert findings[0].citation.doc_id == "LCD_VECTOR_001"


def test_vector_results_convert_to_policy_like_objects(mock_vector_store):
    """_vector_result_to_policy() maps chunk fields onto the keys _build_user_message() reads."""
    from agents.coverage_validation import _vector_result_to_policy

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


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_citation_grounding_works_with_vector_result_document_id(mock_anthropic, mock_vector_store, monkeypatch):
    """Citation grounding (doc_id must be in the retrieved set) applies identically to vector-sourced policies."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 2
    mock_vector_store.query.return_value = [_vector_chunk("LCD_VECTOR_003", "Real retrieved text.")]

    tool_block = _tool_use_block("report_coverage_finding", {
        "issue": "Hallucinated concern",
        "recommendation": "Fix it.",
        "severity": "HIGH",
        "confidence": 0.9,
        "citation_doc_id": "LCD_NOT_RETRIEVED",  # not in the vector result set
        "citation_section": "Section X",
        "citation_excerpt": "hallucinated text",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))
    assert findings == []  # suppressed: ungrounded doc_id, even though the source was the vector store


def test_json_fallback_used_when_vector_store_returns_empty_list(mock_vector_store):
    """vector_store.count() > 0 but query() returns [] (e.g. no chunk relevant to this claim) -> JSON fallback."""
    from agents.coverage_validation import _retrieve_policies

    mock_vector_store.count.return_value = 5
    mock_vector_store.query.return_value = []

    policies = _retrieve_policies(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    mock_vector_store.query.assert_called_once()
    assert policies  # JSON corpus has a match for Z00.00
    assert all(p["document_id"] != "" for p in policies)


def test_json_fallback_used_when_vector_store_count_is_zero(mock_vector_store):
    """Default fixture state: count()==0 short-circuits before query() is even called."""
    from agents.coverage_validation import _retrieve_policies

    policies = _retrieve_policies(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    mock_vector_store.query.assert_not_called()
    assert policies  # JSON corpus has a match for Z00.00


def test_json_fallback_used_when_vector_store_raises(mock_vector_store):
    """vector_store.query() raising (e.g. ChromaDB unavailable) falls back to JSON, never propagates."""
    from agents.coverage_validation import _retrieve_policies

    mock_vector_store.count.return_value = 5
    mock_vector_store.query.side_effect = RuntimeError("ChromaDB connection lost")

    policies = _retrieve_policies(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    assert policies  # JSON corpus has a match for Z00.00


def test_no_policy_from_vector_or_json_returns_empty_list(mock_vector_store):
    """Neither source has anything for these codes -> []."""
    from agents.coverage_validation import _retrieve_policies

    mock_vector_store.count.return_value = 5
    mock_vector_store.query.return_value = []

    policies = _retrieve_policies(_claim(cpt_codes=["ZZZZ99"], icd10_codes=["Q00.0"]))
    assert policies == []


def test_validate_coverage_returns_empty_when_neither_source_has_policies(monkeypatch, mock_vector_store):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 5
    mock_vector_store.query.return_value = []

    findings = validate_coverage(_claim(cpt_codes=["ZZZZ99"], icd10_codes=["Q00.0"]))
    assert findings == []


def test_vector_store_not_queried_when_claim_has_no_codes(mock_vector_store, monkeypatch):
    """Empty query text short-circuits before touching the vector store at all."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from agents.coverage_validation import _retrieve_from_vector_store

    result = _retrieve_from_vector_store(_claim())
    mock_vector_store.count.assert_not_called()
    assert result == []


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_existing_mocked_anthropic_flow_unaffected_by_vector_swap(mock_anthropic, monkeypatch, mock_vector_store):
    """Sanity check: with the vector store empty (default), v1 behavior is bit-for-bit preserved."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_block = _tool_use_block("report_coverage_finding", {
        "issue": "E/M billed with preventive diagnosis only",
        "recommendation": "Add modifier 25 and a separate problem diagnosis.",
        "severity": "MEDIUM",
        "confidence": 0.85,
        "citation_doc_id": "LCD_E_M_MEDICAL_NECESSITY_Z00",
        "citation_section": "Indications and Limitations of Coverage and/or Medical Necessity",
        "citation_excerpt": "Problem-oriented E/M services billed with Z00.00 require modifier 25.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coverage(_claim(cpt_codes=["99213"], icd10_codes=["Z00.00"]))

    assert len(findings) == 1
    assert findings[0].citation.doc_id == "LCD_E_M_MEDICAL_NECESSITY_Z00"


# ---------------------------------------------------------------------------
# Excerpt quality fix: dangling-fragment cleanup and fallback to chunk text
# ---------------------------------------------------------------------------

def test_clean_citation_excerpt_keeps_clean_model_excerpt_unchanged():
    from agents.coverage_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt(
        "Problem-oriented E/M services billed with Z00.00 require modifier 25.",
        fallback_chunk_text="irrelevant fallback text.",
    )
    assert result == "Problem-oriented E/M services billed with Z00.00 require modifier 25."


def test_clean_citation_excerpt_falls_back_when_model_excerpt_starts_with_dangling_paren():
    from agents.coverage_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt(
        "). This NCD lists the ICD-10 codes for HbA1c for frequencies up to once every 3 months.",
        fallback_chunk_text="HbA1c testing is reasonable and necessary for stable glycemic control patients.",
    )
    assert result == "HbA1c testing is reasonable and necessary for stable glycemic control patients."
    assert not result.startswith(")")


def test_clean_citation_excerpt_falls_back_when_model_excerpt_is_empty():
    from agents.coverage_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt("", fallback_chunk_text="Clean fallback sentence.")
    assert result == "Clean fallback sentence."


def test_clean_citation_excerpt_returns_dangling_text_if_no_fallback_available():
    """With no fallback at all, return whatever the model gave rather than an empty string."""
    from agents.coverage_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt(") dangling model text.", fallback_chunk_text="")
    assert result == ") dangling model text."


# ---------------------------------------------------------------------------
# TD-26: low-information excerpt handling
# ---------------------------------------------------------------------------

def test_clean_citation_excerpt_falls_back_when_model_excerpt_is_low_information():
    """The real, observed TD-26 weak excerpt: complete sentence, no substance."""
    from agents.coverage_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt(
        "Scroll down for links to the quarterly Covered Code Lists (including narrative).",
        fallback_chunk_text="HbA1c testing is reasonable and necessary for stable glycemic control patients.",
    )
    assert result == "HbA1c testing is reasonable and necessary for stable glycemic control patients."


def test_clean_citation_excerpt_returns_low_information_text_if_no_better_fallback():
    """With no substantive fallback available, still return something rather than an empty excerpt."""
    from agents.coverage_validation import _clean_citation_excerpt

    result = _clean_citation_excerpt("Scroll down for links to the quarterly Covered Code Lists.", fallback_chunk_text="")
    assert result == "Scroll down for links to the quarterly Covered Code Lists."


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_vector_citation_excerpt_does_not_begin_with_dangling_paren(mock_anthropic, mock_vector_store, monkeypatch):
    """
    Regression test for the production bug: the model echoes a vector chunk that
    happened to start right after a closing paren ("). This NCD lists..."). The
    finding's citation.excerpt must not surface that fragment verbatim.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 1
    mock_vector_store.query.return_value = [_vector_chunk(
        "33431",
        "). This NCD lists the ICD-10 codes for HbA1c for frequencies up to once every 3 months.",
        document_title="HbA1c",
    )]

    tool_block = _tool_use_block("report_coverage_finding", {
        "issue": "HbA1c lacks medical necessity diagnosis",
        "recommendation": "Add a diabetes diagnosis code.",
        "severity": "HIGH",
        "confidence": 0.9,
        "citation_doc_id": "33431",
        "citation_section": "Coverage Indications, Limitations, and/or Medical Necessity",
        "citation_excerpt": "). This NCD lists the ICD-10 codes for HbA1c for frequencies up to once every 3 months.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coverage(_claim(cpt_codes=["83036"], icd10_codes=["Z00.00"]))

    assert len(findings) == 1
    excerpt = findings[0].citation.excerpt
    assert not excerpt.startswith(")")
    assert not excerpt.startswith(".")
    assert excerpt == "This NCD lists the ICD-10 codes for HbA1c for frequencies up to once every 3 months."


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_vector_citation_grounding_still_passes_with_clean_excerpt(mock_anthropic, mock_vector_store, monkeypatch):
    """The excerpt cleanup must not interfere with citation grounding — doc_id matching is unaffected."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_vector_store.count.return_value = 1
    mock_vector_store.query.return_value = [_vector_chunk(
        "33431", "HbA1c testing is reasonable and necessary for stable glycemic control.",
        document_title="HbA1c",
    )]

    tool_block = _tool_use_block("report_coverage_finding", {
        "issue": "Medical necessity concern",
        "recommendation": "Review documentation.",
        "severity": "MEDIUM",
        "confidence": 0.8,
        "citation_doc_id": "33431",
        "citation_section": "Coverage Indications, Limitations, and/or Medical Necessity",
        "citation_excerpt": "HbA1c testing is reasonable and necessary for stable glycemic control.",
    })
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    findings = validate_coverage(_claim(cpt_codes=["83036"], icd10_codes=["Z00.00"]))

    assert len(findings) == 1
    assert findings[0].citation.doc_id == "33431"
    assert findings[0].citation.excerpt == "HbA1c testing is reasonable and necessary for stable glycemic control."


# ---------------------------------------------------------------------------
# Tests: TD-24 Phase 3 — anti-pile-on prompt guidance
# ---------------------------------------------------------------------------

def _rule_finding(rule="ncci_conflict"):
    return Finding(
        rule=rule,
        severity="HIGH",
        issue="Test rule-layer finding",
        recommendation="Test recommendation",
        citation=Citation(source="NCCI PTP", doc_id="test-doc", section="Test Section", edition="test"),
        confidence=0.9,
        source="rule_layer",
    )


def test_system_prompt_instructs_not_to_duplicate_rule_layer_findings():
    """TD-24 Phase 3: system prompt must tell the model not to restate rule-layer findings."""
    assert "Do not restate or duplicate" in _SYSTEM_PROMPT
    assert "no_coverage_concern" in _SYSTEM_PROMPT
    assert "genuinely" in _SYSTEM_PROMPT and "distinct" in _SYSTEM_PROMPT


def test_system_prompt_forbids_generic_payer_scrutiny_caveats():
    """TD-24 Phase 3: system prompt must explicitly forbid generic payer-scrutiny cautions."""
    assert "generic payer-scrutiny caution" in _SYSTEM_PROMPT


def test_summarize_rule_findings_returns_none_for_empty_or_missing():
    assert _summarize_rule_findings(None) == "none"
    assert _summarize_rule_findings([]) == "none"


def test_summarize_rule_findings_lists_deduplicated_rule_names():
    findings = [_rule_finding("ncci_conflict"), _rule_finding("ncci_conflict"), _rule_finding("mue_limit")]
    assert _summarize_rule_findings(findings) == "ncci_conflict, mue_limit"


def test_build_user_message_includes_rule_findings_line_when_present():
    message = _build_user_message(_claim(cpt_codes=["83036"]), [], [_rule_finding("missing_modifier_25")])
    assert "Rule-layer findings already identified for this claim: missing_modifier_25" in message


def test_build_user_message_reports_none_when_no_rule_findings():
    message = _build_user_message(_claim(cpt_codes=["83036"]), [], None)
    assert "Rule-layer findings already identified for this claim: none" in message


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_validate_coverage_passes_rule_findings_into_prompt(mock_anthropic, monkeypatch):
    """rule_findings passed to validate_coverage() must reach the model's user message."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    tool_block = _tool_use_block("no_coverage_concern", {"reason": "already explained by rule layer"})
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    rule_findings = [_rule_finding("ncci_conflict")]
    validate_coverage(_claim(cpt_codes=["83036"], icd10_codes=["Z00.00"]), rule_findings)

    _, kwargs = mock_anthropic.return_value.messages.create.call_args
    sent_message = kwargs["messages"][0]["content"]
    assert "Rule-layer findings already identified for this claim: ncci_conflict" in sent_message


@patch("agents.coverage_validation.anthropic.Anthropic")
def test_validate_coverage_without_rule_findings_still_works(mock_anthropic, monkeypatch):
    """Omitting rule_findings (default None) preserves prior call behavior exactly."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    tool_block = _tool_use_block("no_coverage_concern", {"reason": "fine"})
    mock_anthropic.return_value.messages.create.return_value = _mock_response(tool_block)

    result = validate_coverage(_claim(cpt_codes=["83036"], icd10_codes=["Z00.00"]))

    assert result == []
    _, kwargs = mock_anthropic.return_value.messages.create.call_args
    sent_message = kwargs["messages"][0]["content"]
    assert "Rule-layer findings already identified for this claim: none" in sent_message
