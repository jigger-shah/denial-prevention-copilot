"""
Document chunking for LCD/NCD policy text.

Splits raw LCD/NCD document records into chunks suitable for embedding and retrieval.
Strategy: section-aware splitting that keeps policy sections (Indications, Limitations,
Covered Diagnoses, Non-Covered Diagnoses, Documentation Requirements) intact rather
than cutting at fixed token counts. This preserves citation integrity — a retrieved
chunk maps to a named, citable section rather than an arbitrary slice.

Input contract (produced by retrieval/ingest.py in a later sprint; tests in this
sprint construct this dict directly since ingest.py is not yet implemented):
    {
        "document_id": str,
        "document_title": str,
        "document_type": str,        # e.g. "LCD", "NCD", "Article"
        "contractor": str | None,
        "effective_date": str | None,
        "sections": [
            {"heading": str, "text": str},
            ...
        ],
    }

Output: list of chunk dicts, each with keys:
    text, document_id, document_title, section_heading, effective_date, chunk_index.

A section whose text exceeds max_chunk_chars is split into multiple chunks (on
paragraph boundaries first, then sentence boundaries within an over-long
paragraph) that all carry the same section_heading, so a citation can always
point back to a named policy section. chunk_index is sequential across the
whole document, not reset per section.

The effective_date flows through to Finding.citation so the UI can show the version
of the policy that was actually consulted.

Chunk text cleanup: section text is run through a defensive, idempotent
HTML-entity unescape and tag strip (real CMS LCD/NCD text is normally already
cleaned by retrieval/ingest.py:_clean_html(), but this is a second line of
defense for text that reaches chunk_document() by any other path — a no-op
on text that's already clean). After splitting, every
piece has its whitespace collapsed and any leading dangling closing-
punctuation/quote character stripped (trim_leading_fragment()) — this matters
because a hard sentence-boundary split can still occasionally land right after
a closing parenthesis or quote (e.g. a parenthetical aside that ends a
sentence), and a chunk that begins "). This NCD lists..." reads as a broken
fragment when shown as a citation excerpt in the UI.
"""

import html
import re

DEFAULT_MAX_CHUNK_CHARS = 1500

REQUIRED_DOCUMENT_KEYS = ("document_id", "sections")

# Characters that indicate a chunk begins mid-sentence, right after something
# else's closing punctuation — stripped from the start of every chunk piece.
DANGLING_LEAD_CHARS = ")]}.,;:!?\"'’”–—"

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def chunk_document(document: dict, max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS) -> list[dict]:
    """
    Split a raw LCD/NCD document record into section-aware chunks.

    Raises ValueError if the document is missing document_id or sections.
    Sections with blank or whitespace-only text are skipped (no chunk emitted).
    """
    missing = [key for key in REQUIRED_DOCUMENT_KEYS if key not in document]
    if missing:
        raise ValueError(f"document is missing required key(s): {missing}")

    document_id = document["document_id"]
    document_title = document.get("document_title", "")
    effective_date = document.get("effective_date")

    chunks = []
    chunk_index = 0
    for section in document["sections"]:
        heading = section.get("heading", "")
        text = _clean_entities((section.get("text") or "").strip())
        if not text:
            continue

        for piece in _split_section_text(text, max_chunk_chars):
            cleaned_piece = _finalize_piece(piece)
            if not cleaned_piece:
                continue
            chunks.append({
                "text": cleaned_piece,
                "document_id": document_id,
                "document_title": document_title,
                "section_heading": heading,
                "effective_date": effective_date,
                "chunk_index": chunk_index,
            })
            chunk_index += 1

    return chunks


def starts_with_dangling_fragment(text: str) -> bool:
    """True if text begins (after whitespace) with closing punctuation/quote — a sign of a mid-sentence cut."""
    stripped = text.lstrip()
    return bool(stripped) and stripped[0] in DANGLING_LEAD_CHARS


def trim_leading_fragment(text: str) -> str:
    """Strip any leading run of dangling closing-punctuation/quote characters left over from a hard split."""
    return text.lstrip(DANGLING_LEAD_CHARS + " ")


def _clean_entities(text: str) -> str:
    """
    Idempotent repeated HTML-entity unescape plus tag stripping — defense in
    depth if text reaches chunk_document() without ingest.py's _clean_html()
    cleanup (e.g. a future non-ingest.py document source). A no-op on text
    that's already clean.
    """
    if not text:
        return text
    unescaped = text
    for _ in range(3):
        next_pass = html.unescape(unescaped)
        if next_pass == unescaped:
            break
        unescaped = next_pass
    return re.sub(r"<[^>]+>", "", unescaped)


def _finalize_piece(text: str) -> str:
    """Post-split cleanup applied to every chunk: collapse stray whitespace, trim a leading dangling fragment."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    return trim_leading_fragment(collapsed).strip()


def _split_section_text(text: str, max_chunk_chars: int) -> list[str]:
    """
    Split section text into pieces no longer than max_chunk_chars.

    Prefers paragraph boundaries (blank-line-separated) to keep ideas intact.
    For a single paragraph that still exceeds max_chunk_chars on its own,
    splits on sentence boundaries (_split_long_paragraph) rather than cutting
    at an arbitrary character offset — this is what prevents a chunk from
    starting mid-sentence.
    """
    if len(text) <= max_chunk_chars:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    pieces = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph

        if len(candidate) <= max_chunk_chars:
            current = candidate
            continue

        if current:
            pieces.append(current)
            current = ""

        if len(paragraph) <= max_chunk_chars:
            current = paragraph
        else:
            pieces.extend(_split_long_paragraph(paragraph, max_chunk_chars))

    if current:
        pieces.append(current)

    return pieces


def _split_long_paragraph(paragraph: str, max_chunk_chars: int) -> list[str]:
    """
    Sentence-aware split for a single paragraph that alone exceeds max_chunk_chars.

    Packs whole sentences into each piece. Only falls back to a hard character
    split if a single sentence by itself still exceeds max_chunk_chars (rare).
    """
    sentences = _SENTENCE_BOUNDARY.split(paragraph)
    pieces = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}" if current else sentence

        if len(candidate) <= max_chunk_chars:
            current = candidate
            continue

        if current:
            pieces.append(current)
            current = ""

        if len(sentence) <= max_chunk_chars:
            current = sentence
        else:
            for start in range(0, len(sentence), max_chunk_chars):
                pieces.append(sentence[start:start + max_chunk_chars])

    if current:
        pieces.append(current)

    return pieces
