"""
Document chunking for LCD/NCD policy text.

Splits raw LCD/NCD document text into chunks suitable for embedding and retrieval.
Strategy: section-aware splitting that keeps policy sections (Indications, Limitations,
Covered Diagnoses, Non-Covered Diagnoses, Documentation Requirements) intact rather
than cutting at fixed token counts. This preserves citation integrity — a retrieved
chunk maps to a named, citable section rather than an arbitrary slice.

Each chunk is a dict with keys:
  text, document_id, document_title, section_heading, effective_date, chunk_index.

The effective_date flows through to Finding.citation so the UI can show the version
of the policy that was actually consulted.
"""
