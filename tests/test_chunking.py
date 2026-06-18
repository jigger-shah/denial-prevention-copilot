"""Tests for retrieval/chunking.py — section-aware LCD/NCD chunking."""

import pytest

from retrieval.chunking import chunk_document, _split_section_text


def _document(sections, **overrides):
    base = {
        "document_id": "LCD_TEST_001",
        "document_title": "Test LCD — Sample Coverage Policy",
        "document_type": "LCD",
        "contractor": "Noridian",
        "effective_date": "2026-01-01",
        "sections": sections,
    }
    base.update(overrides)
    return base


def test_single_small_section_produces_one_chunk():
    doc = _document([{"heading": "Indications and Limitations of Coverage", "text": "Short policy text."}])
    chunks = chunk_document(doc)

    assert len(chunks) == 1
    assert chunks[0]["text"] == "Short policy text."
    assert chunks[0]["document_id"] == "LCD_TEST_001"
    assert chunks[0]["document_title"] == "Test LCD — Sample Coverage Policy"
    assert chunks[0]["section_heading"] == "Indications and Limitations of Coverage"
    assert chunks[0]["effective_date"] == "2026-01-01"
    assert chunks[0]["chunk_index"] == 0


def test_multiple_sections_each_produce_a_chunk_with_sequential_index():
    doc = _document([
        {"heading": "Indications", "text": "Indications text."},
        {"heading": "Limitations", "text": "Limitations text."},
        {"heading": "Documentation Requirements", "text": "Documentation text."},
    ])
    chunks = chunk_document(doc)

    assert len(chunks) == 3
    assert [c["section_heading"] for c in chunks] == ["Indications", "Limitations", "Documentation Requirements"]
    assert [c["chunk_index"] for c in chunks] == [0, 1, 2]
    assert all(c["document_id"] == "LCD_TEST_001" for c in chunks)


def test_long_section_splits_into_multiple_chunks_with_same_heading():
    paragraph = "This sentence repeats to build a long paragraph. " * 10  # ~510 chars
    long_text = "\n\n".join([paragraph] * 5)  # ~2550+ chars, well over max_chunk_chars
    doc = _document([{"heading": "Covered Diagnoses", "text": long_text}])

    chunks = chunk_document(doc, max_chunk_chars=1000)

    assert len(chunks) > 1
    assert all(c["section_heading"] == "Covered Diagnoses" for c in chunks)
    assert all(len(c["text"]) <= 1000 for c in chunks)
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_chunk_index_is_sequential_across_sections_when_one_section_splits():
    paragraph = "Repeated filler sentence for length. " * 20  # ~760 chars
    long_text = "\n\n".join([paragraph] * 4)
    doc = _document([
        {"heading": "Indications", "text": "Short indications text."},
        {"heading": "Limitations", "text": long_text},
        {"heading": "Documentation Requirements", "text": "Short documentation text."},
    ])

    chunks = chunk_document(doc, max_chunk_chars=1000)

    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    headings_in_order = [c["section_heading"] for c in chunks]
    assert headings_in_order[0] == "Indications"
    assert headings_in_order[-1] == "Documentation Requirements"
    assert headings_in_order.count("Limitations") > 1


def test_blank_section_text_is_skipped():
    doc = _document([
        {"heading": "Indications", "text": "Real text."},
        {"heading": "Empty Section", "text": "   "},
        {"heading": "Missing Text Key"},
    ])
    chunks = chunk_document(doc)

    assert len(chunks) == 1
    assert chunks[0]["section_heading"] == "Indications"


def test_missing_document_id_raises_value_error():
    doc = _document([{"heading": "Indications", "text": "text"}])
    del doc["document_id"]

    with pytest.raises(ValueError, match="document_id"):
        chunk_document(doc)


def test_missing_sections_key_raises_value_error():
    doc = _document([{"heading": "Indications", "text": "text"}])
    del doc["sections"]

    with pytest.raises(ValueError, match="sections"):
        chunk_document(doc)


def test_no_sections_list_produces_no_chunks():
    doc = _document([])
    assert chunk_document(doc) == []


def test_effective_date_and_title_default_to_none_and_empty_string():
    doc = {
        "document_id": "LCD_TEST_002",
        "sections": [{"heading": "Indications", "text": "Some text."}],
    }
    chunks = chunk_document(doc)

    assert chunks[0]["effective_date"] is None
    assert chunks[0]["document_title"] == ""


def test_hard_split_for_single_paragraph_exceeding_max_chunk_chars():
    huge_paragraph = "a" * 3500  # no blank-line breaks at all
    doc = _document([{"heading": "Limitations", "text": huge_paragraph}])

    chunks = chunk_document(doc, max_chunk_chars=1000)

    assert len(chunks) == 4  # 3500 / 1000 -> 4 pieces (1000, 1000, 1000, 500)
    assert all(len(c["text"]) <= 1000 for c in chunks)
    assert "".join(c["text"] for c in chunks) == huge_paragraph


def test_split_section_text_returns_single_piece_when_under_limit():
    assert _split_section_text("short text", 1500) == ["short text"]
