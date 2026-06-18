"""Tests for retrieval/ingest.py — CMS Coverage API client.

No real network calls. requests.get is patched per the same convention used
in tests/test_rules.py for NPPES (MagicMock responses, side_effect for errors).

Response shapes mirror the CMS Coverage API's real {"meta": ..., "data": [...]}
envelope and field names, verified live against api.coverage.cms.gov during
Session 1D (LCD id 33797, NCD id 108, Article id 52514) — see TD-18 in
docs/Technical_Debt_Register.md. LCD and Article additionally require an
Authorization: Bearer token obtained from /v1/metadata/license-agreement;
NCD does not.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from retrieval import ingest
from retrieval.ingest import CoverageAPIError, fetch_article, fetch_lcd, fetch_ncd, save_document


def _mock_response(status_code=200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = text
    return resp


def _envelope(record: dict) -> dict:
    """Wrap a record the way the real CMS Coverage API does: {"meta": ..., "data": [record]}."""
    return {"meta": {"status": {"id": 200, "message": "OK"}, "fields": list(record.keys())}, "data": [record]}


_TOKEN_RECORD = {"Token": "test-token-abc123"}


@pytest.fixture(autouse=True)
def reset_token_cache():
    """The license token is cached at module scope for process lifetime — reset between tests."""
    ingest._token_cache["token"] = None
    yield
    ingest._token_cache["token"] = None


def _token_response():
    return _mock_response(json_body=_envelope(_TOKEN_RECORD))


# ---------------------------------------------------------------------------
# fetch_lcd / fetch_ncd / fetch_article success paths
# ---------------------------------------------------------------------------

def test_fetch_lcd_success_normalizes_and_saves(tmp_path):
    lcd_record = {
        "lcd_id": 33797,
        "title": "Oxygen and Oxygen Equipment",
        "rev_eff_date": "04/01/2023",
        "indication": "&lt;p&gt;Coverage applies when medically necessary.&lt;&sol;p&gt;",
        "doc_reqs": "&lt;p&gt;Document the medical necessity in the note.&lt;&sol;p&gt;",
    }
    responses = [_token_response(), _mock_response(json_body=_envelope(lcd_record))]
    with patch("retrieval.ingest.requests.get", side_effect=responses) as mock_get:
        document = fetch_lcd("33797", output_dir=tmp_path)

    assert document["document_id"] == "33797"
    assert document["document_title"] == "Oxygen and Oxygen Equipment"
    assert document["document_type"] == "LCD"
    assert document["contractor"] is None  # not a field on the LCD record (see ingest.py docstring)
    assert document["effective_date"] == "04/01/2023"
    assert {"heading": "Coverage Indications, Limitations, and/or Medical Necessity",
             "text": "Coverage applies when medically necessary."} in document["sections"]
    assert {"heading": "Documentation Requirements",
             "text": "Document the medical necessity in the note."} in document["sections"]

    # token call + document call
    assert mock_get.call_count == 2
    auth_header = mock_get.call_args_list[1].kwargs["headers"]["Authorization"]
    assert auth_header == "Bearer test-token-abc123"

    saved_path = tmp_path / "LCD_33797.json"
    assert saved_path.exists()
    assert json.loads(saved_path.read_text()) == document


def test_fetch_ncd_success_has_no_contractor_and_no_auth_call(tmp_path):
    ncd_record = {
        "document_id": "108",
        "title": "24-Hour Ambulatory Esophageal pH Monitoring",
        "effective_date": "06/11/1985",
        "indications_limitations": "Covered for diabetes management.",
    }
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=_envelope(ncd_record))) as mock_get:
        document = fetch_ncd("108", output_dir=tmp_path)

    assert document["document_id"] == "108"
    assert document["document_type"] == "NCD"
    assert document["contractor"] is None
    assert document["effective_date"] == "06/11/1985"
    assert mock_get.call_count == 1  # no license-token call for NCD
    assert (tmp_path / "NCD_108.json").exists()


def test_fetch_article_success(tmp_path):
    article_record = {
        "article_id": 52514,
        "title": "Oxygen and Oxygen Equipment - Policy Article",
        "article_eff_date": "04/01/2023",
        "icd9_covered_para": "Z00.00, I10",
    }
    responses = [_token_response(), _mock_response(json_body=_envelope(article_record))]
    with patch("retrieval.ingest.requests.get", side_effect=responses):
        document = fetch_article("52514", output_dir=tmp_path)

    assert document["document_id"] == "52514"
    assert document["document_type"] == "Article"
    assert {"heading": "Covered Diagnoses", "text": "Z00.00, I10"} in document["sections"]
    assert (tmp_path / "Article_52514.json").exists()


# ---------------------------------------------------------------------------
# Caching / offline behavior
# ---------------------------------------------------------------------------

def test_cached_local_file_skips_network_call(tmp_path):
    cached_document = {
        "document_id": "33797", "document_title": "Cached LCD", "document_type": "LCD",
        "contractor": None, "effective_date": "04/01/2023", "sections": [],
    }
    save_document(cached_document, output_dir=tmp_path)

    with patch("retrieval.ingest.requests.get") as mock_get:
        document = fetch_lcd("33797", output_dir=tmp_path)

    mock_get.assert_not_called()
    assert document == cached_document


def test_force_refresh_bypasses_cache_and_calls_network(tmp_path):
    cached_document = {
        "document_id": "33797", "document_title": "Stale Cached LCD", "document_type": "LCD",
        "contractor": None, "effective_date": "04/01/2023", "sections": [],
    }
    save_document(cached_document, output_dir=tmp_path)

    fresh_record = {"lcd_id": 33797, "title": "Refreshed LCD", "rev_eff_date": "01/01/2026"}
    responses = [_token_response(), _mock_response(json_body=_envelope(fresh_record))]
    with patch("retrieval.ingest.requests.get", side_effect=responses) as mock_get:
        document = fetch_lcd("33797", output_dir=tmp_path, force_refresh=True)

    assert mock_get.call_count == 2
    assert document["document_title"] == "Refreshed LCD"


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------

def test_non_retryable_http_error_raises_coverage_api_error(tmp_path):
    responses = [_token_response(), _mock_response(status_code=404, text="Not Found")]
    with patch("retrieval.ingest.requests.get", side_effect=responses):
        with pytest.raises(CoverageAPIError, match="404"):
            fetch_lcd("does-not-exist", output_dir=tmp_path)


def test_connection_error_raises_coverage_api_error_after_retries(tmp_path):
    # NCD requires no token call, so the connection error fires on the first (only) request.
    with patch("retrieval.ingest.requests.get", side_effect=requests.ConnectionError("boom")):
        with patch("retrieval.ingest.time.sleep"):  # skip real backoff delay in tests
            with pytest.raises(CoverageAPIError):
                fetch_ncd("108", output_dir=tmp_path)


# ---------------------------------------------------------------------------
# 429 retry behavior
# ---------------------------------------------------------------------------

def test_429_retries_then_succeeds(tmp_path):
    responses = [
        _mock_response(status_code=429, text="Too Many Requests"),
        _mock_response(status_code=429, text="Too Many Requests"),
        _mock_response(json_body=_envelope({"document_id": "108", "title": "Recovered NCD"})),
    ]
    with patch("retrieval.ingest.requests.get", side_effect=responses) as mock_get:
        with patch("retrieval.ingest.time.sleep") as mock_sleep:
            document = fetch_ncd("108", output_dir=tmp_path)

    assert document["document_title"] == "Recovered NCD"
    assert mock_get.call_count == 3
    assert mock_sleep.call_count == 2


def test_429_exhausts_retries_raises_coverage_api_error(tmp_path):
    always_429 = _mock_response(status_code=429, text="Too Many Requests")
    with patch("retrieval.ingest.requests.get", return_value=always_429) as mock_get:
        with patch("retrieval.ingest.time.sleep"):
            with pytest.raises(CoverageAPIError):
                fetch_ncd("108", output_dir=tmp_path)

    assert mock_get.call_count == ingest.MAX_RETRIES


# ---------------------------------------------------------------------------
# Missing optional fields
# ---------------------------------------------------------------------------

def test_missing_optional_fields_default_gracefully(tmp_path):
    ncd_record = {"document_id": "108"}  # no title, no effective_date, no sections
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=_envelope(ncd_record))):
        document = fetch_ncd("108", output_dir=tmp_path)

    assert document["document_title"] == ""
    assert document["contractor"] is None
    assert document["effective_date"] is None
    assert document["sections"] == []


def test_missing_id_field_defaults_to_empty_string(tmp_path):
    ncd_record = {"title": "No ID NCD"}
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=_envelope(ncd_record))):
        document = fetch_ncd("ignored-when-missing", output_dir=tmp_path)

    assert document["document_title"] == "No ID NCD"
    assert document["document_id"] == ""


def test_empty_data_list_defaults_entire_record_gracefully(tmp_path):
    """The CMS API returns an empty data list (not an error) when an ID doesn't exist."""
    empty_envelope = {"meta": {"status": {"id": 200, "message": "OK"}, "notes": "0 results"}, "data": []}
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=empty_envelope)):
        document = fetch_ncd("does-not-exist", output_dir=tmp_path)

    assert document["document_id"] == ""
    assert document["document_title"] == ""
    assert document["sections"] == []


# ---------------------------------------------------------------------------
# HTML cleanup
# ---------------------------------------------------------------------------

def test_double_encoded_html_entities_are_cleaned(tmp_path):
    ncd_record = {
        "document_id": "108",
        "title": "Test",
        "indications_limitations": "&lt;p&gt;The &amp;ldquo;reasonable&amp;rdquo; criteria apply.&lt;&sol;p&gt;",
    }
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=_envelope(ncd_record))):
        document = fetch_ncd("108", output_dir=tmp_path)

    text = document["sections"][0]["text"]
    assert "&lt;" not in text
    assert "&amp;" not in text
    assert "<p>" not in text
    assert "“reasonable”" in text or '"reasonable"' in text


# ---------------------------------------------------------------------------
# save_document raw JSON shape
# ---------------------------------------------------------------------------

def test_save_document_writes_raw_json_to_coverage_directory(tmp_path):
    document = {
        "document_id": "108", "document_title": "Test NCD", "document_type": "NCD",
        "contractor": None, "effective_date": "06/11/1985",
        "sections": [{"heading": "Indications", "text": "Some text."}],
    }
    path = save_document(document, output_dir=tmp_path)

    assert path == tmp_path / "NCD_108.json"
    assert json.loads(path.read_text()) == document


# ---------------------------------------------------------------------------
# CLI dry-run
# ---------------------------------------------------------------------------

def test_cli_dry_run_does_not_call_network(tmp_path, capsys):
    from scripts.ingest_coverage import main

    with patch("retrieval.ingest.requests.get") as mock_get:
        exit_code = main(["--type", "ncd", "--id", "108", "--dry-run", "--output-dir", str(tmp_path)])

    mock_get.assert_not_called()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "dry-run" in captured.out
    assert "108" in captured.out
    assert not (tmp_path / "NCD_108.json").exists()


def test_cli_fetches_and_reports_success(tmp_path, capsys):
    from scripts.ingest_coverage import main

    ncd_record = {"document_id": "108", "title": "CLI Test NCD", "indications_limitations": "Some indication text."}
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=_envelope(ncd_record))):
        exit_code = main(["--type", "ncd", "--id", "108", "--output-dir", str(tmp_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Ingested NCD 108" in captured.out
    assert (tmp_path / "NCD_108.json").exists()


def test_cli_reports_error_on_http_failure(tmp_path, capsys):
    from scripts.ingest_coverage import main

    with patch("retrieval.ingest.requests.get", return_value=_mock_response(status_code=404, text="Not Found")):
        exit_code = main(["--type", "ncd", "--id", "missing", "--output-dir", str(tmp_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error" in captured.err
