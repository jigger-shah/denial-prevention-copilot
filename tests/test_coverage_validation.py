"""
Tests for agents/coverage_validation.py — all model calls are mocked.

No real Anthropic API calls are made. The mock replaces
`agents.coverage_validation.anthropic.Anthropic` so the client
is never actually instantiated.
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.coverage_validation import validate_coverage, _stable_finding_id
from rules.models import ClaimIn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
