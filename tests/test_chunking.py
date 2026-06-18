"""Tests for retrieval/chunking.py — section-aware LCD/NCD chunking."""

import pytest

from retrieval.chunking import (
    chunk_document,
    starts_with_dangling_fragment,
    trim_leading_fragment,
    _split_section_text,
)


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


# ---------------------------------------------------------------------------
# Excerpt quality fix: HTML/entity cleanup, dangling fragments, sentence boundaries
# ---------------------------------------------------------------------------

def test_double_encoded_html_entities_are_cleaned_defensively():
    """Defense in depth: chunking.py cleans entities even if ingest.py's cleanup was bypassed."""
    doc = _document([{
        "heading": "Indications",
        "text": "&lt;p&gt;The &amp;ldquo;reasonable&amp;rdquo; criteria apply.&lt;&sol;p&gt;",
    }])
    chunks = chunk_document(doc)

    text = chunks[0]["text"]
    assert "&lt;" not in text
    assert "&amp;" not in text
    assert "<p>" not in text
    assert "“reasonable”" in text or '"reasonable"' in text


def test_long_section_real_world_fragment_does_not_start_with_dangling_paren():
    """
    Regression test for the exact production bug: a long single-paragraph
    section (no \\n\\n breaks) that previously hard-split at a fixed character
    offset, landing a new chunk right after a closing parenthesis.
    """
    text = (
        "Performance of the test is supported by clinical guidelines "
        "(see the referenced standards for details). "
        "This NCD lists the ICD-10 codes for the test for frequencies up to once every 3 months. "
    ) * 15  # force this over max_chunk_chars without any paragraph breaks
    doc = _document([{"heading": "Indications", "text": text}])

    chunks = chunk_document(doc, max_chunk_chars=300)

    assert len(chunks) > 1
    for chunk in chunks:
        assert not starts_with_dangling_fragment(chunk["text"]), (
            f"chunk starts with a dangling fragment: {chunk['text'][:40]!r}"
        )


def test_sentence_boundary_split_keeps_sentences_whole():
    text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
    doc = _document([{"heading": "Indications", "text": text}])

    chunks = chunk_document(doc, max_chunk_chars=45)

    assert len(chunks) > 1
    for chunk in chunks:
        stripped = chunk["text"].strip()
        assert stripped[0].isupper() or stripped[0].isdigit(), f"chunk does not start cleanly: {stripped[:40]!r}"
        assert stripped.endswith(".")


def test_starts_with_dangling_fragment_detects_closing_punctuation():
    assert starts_with_dangling_fragment(") This NCD lists the ICD-10 codes.")
    assert starts_with_dangling_fragment(". Continued sentence.")
    assert starts_with_dangling_fragment("”He said this.")
    assert not starts_with_dangling_fragment("This starts cleanly.")


def test_trim_leading_fragment_strips_only_leading_dangling_chars():
    assert trim_leading_fragment(") This NCD lists the codes.") == "This NCD lists the codes."
    assert trim_leading_fragment("Clean sentence (with parens).") == "Clean sentence (with parens)."
    assert trim_leading_fragment("...") == ""


def test_no_chunk_in_real_lcd_text_begins_with_dangling_punctuation():
    """End-to-end shape of the actual production bug: one long, paragraph-break-free LCD section."""
    real_shaped_text = (
        "Hemoglobin A1c (HbA1c) refers to the major component of hemoglobin A1. "
        "Performance of the HbA1c test at least 2 times a year in patients who are meeting "
        "treatment goals and who have stable glycemic control is supported by the American "
        "Diabetes Association Standards of Medical Care in Diabetes (ADA Standards). "
        "For beneficiaries with stable glycemic control (defined as 2 consecutive HbA1c "
        "results meeting the treatment goals) performing the HbA1c test at least 2 times "
        "a year may be considered reasonable and necessary. "
        "Other tests to assess diabetes, including glucose, glycated protein, or fructosamine "
        "levels, may be used and are described in the Lab National Coverage Determination "
        "190.21 (NCD for Glycated Hemoglobin / Glycated Protein). "
        "This NCD lists the ICD-10 codes for HbA1c for frequencies up to once every 3 months."
    )
    doc = _document([{"heading": "Coverage Indications", "text": real_shaped_text}])

    chunks = chunk_document(doc, max_chunk_chars=300)

    assert len(chunks) > 1
    for chunk in chunks:
        assert not chunk["text"].startswith(")")
        assert not chunk["text"].startswith(".")
        assert not starts_with_dangling_fragment(chunk["text"])
