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
paragraph boundaries where possible) that all carry the same section_heading, so
a citation can always point back to a named policy section. chunk_index is
sequential across the whole document, not reset per section.

The effective_date flows through to Finding.citation so the UI can show the version
of the policy that was actually consulted.
"""

DEFAULT_MAX_CHUNK_CHARS = 1500

REQUIRED_DOCUMENT_KEYS = ("document_id", "sections")


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
        text = (section.get("text") or "").strip()
        if not text:
            continue

        for piece in _split_section_text(text, max_chunk_chars):
            chunks.append({
                "text": piece,
                "document_id": document_id,
                "document_title": document_title,
                "section_heading": heading,
                "effective_date": effective_date,
                "chunk_index": chunk_index,
            })
            chunk_index += 1

    return chunks


def _split_section_text(text: str, max_chunk_chars: int) -> list[str]:
    """
    Split section text into pieces no longer than max_chunk_chars.

    Prefers paragraph boundaries (blank-line-separated) to keep ideas intact.
    Falls back to a hard character split for a single paragraph that still
    exceeds max_chunk_chars on its own.
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
            for start in range(0, len(paragraph), max_chunk_chars):
                pieces.append(paragraph[start:start + max_chunk_chars])

    if current:
        pieces.append(current)

    return pieces
