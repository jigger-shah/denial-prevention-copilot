"""Tests for retrieval/ingest.py — CMS Coverage API client.

No real network calls. requests.get is patched per the same convention used
in tests/test_rules.py for NPPES (MagicMock responses, side_effect for errors).
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
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# fetch_lcd / fetch_ncd / fetch_article success paths
# ---------------------------------------------------------------------------

def test_fetch_lcd_success_normalizes_and_saves(tmp_path):
    raw = {
        "lcd_id": "33797",
        "title": "Venipuncture",
        "contractor_name": "Noridian",
        "original_effective_date": "2025-07-01",
        "indication_limitation": "Coverage applies when medically necessary.",
        "documentation_requirements": "Document the medical necessity in the note.",
    }
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=raw)):
        document = fetch_lcd("33797", output_dir=tmp_path)

    assert document["document_id"] == "33797"
    assert document["document_title"] == "Venipuncture"
    assert document["document_type"] == "LCD"
    assert document["contractor"] == "Noridian"
    assert document["effective_date"] == "2025-07-01"
    assert {"heading": "Indications and Limitations of Coverage",
             "text": "Coverage applies when medically necessary."} in document["sections"]
    assert {"heading": "Documentation Requirements",
             "text": "Document the medical necessity in the note."} in document["sections"]

    saved_path = tmp_path / "LCD_33797.json"
    assert saved_path.exists()
    assert json.loads(saved_path.read_text()) == document


def test_fetch_ncd_success_has_no_contractor(tmp_path):
    raw = {
        "ncd_id": "190.33",
        "title": "Glycated Hemoglobin/Glycated Protein",
        "effective_date": "2023-01-01",
        "coverage_indications": "Covered for diabetes management.",
    }
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=raw)):
        document = fetch_ncd("190.33", output_dir=tmp_path)

    assert document["document_id"] == "190.33"
    assert document["document_type"] == "NCD"
    assert document["contractor"] is None
    assert document["effective_date"] == "2023-01-01"
    assert (tmp_path / "NCD_190.33.json").exists()


def test_fetch_article_success(tmp_path):
    raw = {
        "article_id": "A57699",
        "title": "Billing and Coding: Venipuncture",
        "contractor_name": "Noridian",
        "original_effective_date": "2025-07-01",
        "covered_codes": "Z00.00, I10",
    }
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=raw)):
        document = fetch_article("A57699", output_dir=tmp_path)

    assert document["document_id"] == "A57699"
    assert document["document_type"] == "Article"
    assert {"heading": "Covered ICD-10 Codes", "text": "Z00.00, I10"} in document["sections"]
    assert (tmp_path / "Article_A57699.json").exists()


# ---------------------------------------------------------------------------
# Caching / offline behavior
# ---------------------------------------------------------------------------

def test_cached_local_file_skips_network_call(tmp_path):
    cached_document = {
        "document_id": "33797", "document_title": "Cached LCD", "document_type": "LCD",
        "contractor": "Noridian", "effective_date": "2025-07-01", "sections": [],
    }
    save_document(cached_document, output_dir=tmp_path)

    with patch("retrieval.ingest.requests.get") as mock_get:
        document = fetch_lcd("33797", output_dir=tmp_path)

    mock_get.assert_not_called()
    assert document == cached_document


def test_force_refresh_bypasses_cache_and_calls_network(tmp_path):
    cached_document = {
        "document_id": "33797", "document_title": "Stale Cached LCD", "document_type": "LCD",
        "contractor": "Noridian", "effective_date": "2025-07-01", "sections": [],
    }
    save_document(cached_document, output_dir=tmp_path)

    fresh_raw = {"lcd_id": "33797", "title": "Refreshed LCD", "original_effective_date": "2026-01-01"}
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=fresh_raw)) as mock_get:
        document = fetch_lcd("33797", output_dir=tmp_path, force_refresh=True)

    mock_get.assert_called_once()
    assert document["document_title"] == "Refreshed LCD"


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------

def test_non_retryable_http_error_raises_coverage_api_error(tmp_path):
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(status_code=404, text="Not Found")):
        with pytest.raises(CoverageAPIError, match="404"):
            fetch_lcd("does-not-exist", output_dir=tmp_path)


def test_connection_error_raises_coverage_api_error_after_retries(tmp_path):
    with patch("retrieval.ingest.requests.get", side_effect=requests.ConnectionError("boom")):
        with patch("retrieval.ingest.time.sleep"):  # skip real backoff delay in tests
            with pytest.raises(CoverageAPIError):
                fetch_lcd("33797", output_dir=tmp_path)


# ---------------------------------------------------------------------------
# 429 retry behavior
# ---------------------------------------------------------------------------

def test_429_retries_then_succeeds(tmp_path):
    responses = [
        _mock_response(status_code=429, text="Too Many Requests"),
        _mock_response(status_code=429, text="Too Many Requests"),
        _mock_response(status_code=200, json_body={"lcd_id": "33797", "title": "Recovered LCD"}),
    ]
    with patch("retrieval.ingest.requests.get", side_effect=responses) as mock_get:
        with patch("retrieval.ingest.time.sleep") as mock_sleep:
            document = fetch_lcd("33797", output_dir=tmp_path)

    assert document["document_title"] == "Recovered LCD"
    assert mock_get.call_count == 3
    assert mock_sleep.call_count == 2


def test_429_exhausts_retries_raises_coverage_api_error(tmp_path):
    always_429 = _mock_response(status_code=429, text="Too Many Requests")
    with patch("retrieval.ingest.requests.get", return_value=always_429) as mock_get:
        with patch("retrieval.ingest.time.sleep"):
            with pytest.raises(CoverageAPIError):
                fetch_lcd("33797", output_dir=tmp_path)

    assert mock_get.call_count == ingest.MAX_RETRIES


# ---------------------------------------------------------------------------
# Missing optional fields
# ---------------------------------------------------------------------------

def test_missing_optional_fields_default_gracefully(tmp_path):
    raw = {"lcd_id": "33797"}  # no title, no contractor, no effective_date, no sections
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=raw)):
        document = fetch_lcd("33797", output_dir=tmp_path)

    assert document["document_title"] == ""
    assert document["contractor"] is None
    assert document["effective_date"] is None
    assert document["sections"] == []


def test_missing_id_field_defaults_to_empty_string(tmp_path):
    raw = {"title": "No ID LCD"}
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=raw)):
        document = fetch_lcd("ignored-when-missing", output_dir=tmp_path)

    assert document["document_title"] == "No ID LCD"
    assert document["document_id"] == ""


# ---------------------------------------------------------------------------
# save_document raw JSON shape
# ---------------------------------------------------------------------------

def test_save_document_writes_raw_json_to_coverage_directory(tmp_path):
    document = {
        "document_id": "190.33", "document_title": "Test NCD", "document_type": "NCD",
        "contractor": None, "effective_date": "2023-01-01",
        "sections": [{"heading": "Indications", "text": "Some text."}],
    }
    path = save_document(document, output_dir=tmp_path)

    assert path == tmp_path / "NCD_190.33.json"
    assert json.loads(path.read_text()) == document


# ---------------------------------------------------------------------------
# CLI dry-run
# ---------------------------------------------------------------------------

def test_cli_dry_run_does_not_call_network(tmp_path, capsys):
    from scripts.ingest_coverage import main

    with patch("retrieval.ingest.requests.get") as mock_get:
        exit_code = main(["--type", "lcd", "--id", "33797", "--dry-run", "--output-dir", str(tmp_path)])

    mock_get.assert_not_called()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "dry-run" in captured.out
    assert "33797" in captured.out
    assert not (tmp_path / "LCD_33797.json").exists()


def test_cli_fetches_and_reports_success(tmp_path, capsys):
    from scripts.ingest_coverage import main

    raw = {"lcd_id": "33797", "title": "CLI Test LCD", "indication_limitation": "Some indication text."}
    with patch("retrieval.ingest.requests.get", return_value=_mock_response(json_body=raw)):
        exit_code = main(["--type", "lcd", "--id", "33797", "--output-dir", str(tmp_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Ingested LCD 33797" in captured.out
    assert (tmp_path / "LCD_33797.json").exists()


def test_cli_reports_error_on_http_failure(tmp_path, capsys):
    from scripts.ingest_coverage import main

    with patch("retrieval.ingest.requests.get", return_value=_mock_response(status_code=404, text="Not Found")):
        exit_code = main(["--type", "lcd", "--id", "missing", "--output-dir", str(tmp_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error" in captured.err
