"""Tests for retrieval/vector_store.py — ChromaDB wrapper.

All tests use tmp_path for a fully isolated ChromaDB instance per test.
No real CMS data is seeded — chunks are constructed directly in-test, in the
shape produced by retrieval/chunking.py:chunk_document().
"""

import pytest

import retrieval.vector_store as vector_store_module
from retrieval.vector_store import VectorStore


def _chunk(document_id, chunk_index, text, section_heading="Indications", **overrides):
    base = {
        "text": text,
        "document_id": document_id,
        "document_title": f"Title for {document_id}",
        "section_heading": section_heading,
        "effective_date": "2026-01-01",
        "chunk_index": chunk_index,
    }
    base.update(overrides)
    return base


@pytest.fixture
def store(tmp_path):
    return VectorStore(persist_directory=tmp_path)


def test_index_returns_count_of_chunks_indexed(store):
    chunks = [
        _chunk("LCD_001", 0, "Coverage applies to adults with diabetes."),
        _chunk("LCD_001", 1, "Documentation must include an A1C result."),
    ]
    assert store.index(chunks) == 2
    assert store.count() == 2


def test_index_empty_list_is_a_noop(store):
    assert store.index([]) == 0
    assert store.count() == 0


def test_query_returns_plain_dicts_not_chromadb_native_structure(store):
    store.index([_chunk("LCD_001", 0, "Coverage applies to adults with diabetes mellitus.")])

    results = store.query("diabetes coverage", n_results=1)

    assert isinstance(results, list)
    assert isinstance(results[0], dict)
    assert set(results[0].keys()) == {
        "document_id", "document_title", "section_heading",
        "effective_date", "chunk_index", "text", "distance",
    }
    assert "ids" not in results[0]
    assert "metadatas" not in results[0]


def test_query_preserves_citation_required_metadata(store):
    store.index([_chunk(
        "LCD_99999", 3, "Indications text for venipuncture.",
        section_heading="Indications and Limitations of Coverage",
        document_title="LCD L12345 — Venipuncture",
        effective_date="2025-07-01",
    )])

    result = store.query("venipuncture", n_results=1)[0]

    assert result["document_id"] == "LCD_99999"
    assert result["document_title"] == "LCD L12345 — Venipuncture"
    assert result["section_heading"] == "Indications and Limitations of Coverage"
    assert result["effective_date"] == "2025-07-01"
    assert result["chunk_index"] == 3
    assert "venipuncture" in result["text"].lower()


def test_query_on_empty_index_returns_empty_list(store):
    assert store.query("anything", n_results=5) == []


def test_reindexing_same_chunk_is_idempotent_not_duplicated(store):
    chunk = _chunk("LCD_001", 0, "Original text about hypertension management.")
    store.index([chunk])
    assert store.count() == 1

    updated_chunk = _chunk("LCD_001", 0, "Updated text about hypertension management and lifestyle.")
    store.index([updated_chunk])

    assert store.count() == 1
    result = store.query("hypertension", n_results=1)[0]
    assert result["text"] == "Updated text about hypertension management and lifestyle."


def test_reindexing_across_separate_index_calls_does_not_duplicate(store):
    for _ in range(3):
        store.index([_chunk("LCD_001", 0, "Repeated indexing of the same chunk.")])
    assert store.count() == 1


def test_query_n_results_limits_returned_chunks(store):
    chunks = [_chunk("LCD_001", i, f"Chunk number {i} about preventive care.") for i in range(5)]
    store.index(chunks)

    results = store.query("preventive care", n_results=2)
    assert len(results) == 2


def test_query_n_results_capped_to_available_count_without_error(store):
    store.index([_chunk("LCD_001", 0, "Only one chunk in the index.")])

    results = store.query("anything", n_results=10)
    assert len(results) == 1


def test_query_with_filter_restricts_to_matching_document_id(store):
    store.index([
        _chunk("LCD_AAA", 0, "Coverage for condition A."),
        _chunk("LCD_BBB", 0, "Coverage for condition A as well."),
    ])

    results = store.query("coverage for condition A", n_results=5, filters={"document_id": "LCD_BBB"})

    assert len(results) == 1
    assert results[0]["document_id"] == "LCD_BBB"


def test_two_vector_stores_with_different_persist_directories_are_isolated(tmp_path):
    dir_a = tmp_path / "store_a"
    dir_b = tmp_path / "store_b"
    store_a = VectorStore(persist_directory=dir_a)
    store_b = VectorStore(persist_directory=dir_b)

    store_a.index([_chunk("LCD_001", 0, "Only in store A.")])

    assert store_a.count() == 1
    assert store_b.count() == 0


def test_indexing_chunks_from_multiple_documents(store):
    chunks = [
        _chunk("LCD_001", 0, "First document chunk."),
        _chunk("LCD_002", 0, "Second document chunk."),
        _chunk("LCD_002", 1, "Second document, second chunk."),
    ]
    assert store.index(chunks) == 3
    assert store.count() == 3


# ---------------------------------------------------------------------------
# Graceful degradation when chromadb fails to import (e.g. a hosted runtime
# where the chromadb -> opentelemetry -> protobuf import chain raises
# TypeError rather than ImportError — see retrieval/vector_store.py module
# docstring). The module itself must always stay importable; only
# constructing a VectorStore should fail, and only with a clear RuntimeError.
# ---------------------------------------------------------------------------

def test_module_is_importable_even_when_chromadb_failed_to_import():
    """The try/except around `import chromadb` must catch broad Exception,
    not just ImportError, since the observed hosted failure is a TypeError
    raised deep in a generated protobuf module."""
    assert hasattr(vector_store_module, "CHROMADB_IMPORT_ERROR")


def test_vector_store_raises_clear_runtime_error_when_chromadb_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(vector_store_module, "chromadb", None)
    monkeypatch.setattr(vector_store_module, "CHROMADB_IMPORT_ERROR", TypeError("simulated protobuf failure"))

    with pytest.raises(RuntimeError, match="ChromaDB unavailable"):
        VectorStore(persist_directory=tmp_path)


def test_vector_store_runtime_error_chains_the_original_import_failure(monkeypatch, tmp_path):
    """The original import failure must be preserved via exception chaining
    (`raise ... from CHROMADB_IMPORT_ERROR`) so it's still visible in logs/tracebacks."""
    original = TypeError("simulated protobuf failure")
    monkeypatch.setattr(vector_store_module, "chromadb", None)
    monkeypatch.setattr(vector_store_module, "CHROMADB_IMPORT_ERROR", original)

    with pytest.raises(RuntimeError) as exc_info:
        VectorStore(persist_directory=tmp_path)

    assert exc_info.value.__cause__ is original


def test_vector_store_still_works_normally_when_chromadb_is_available(tmp_path):
    """Sanity check: the defensive import doesn't change behavior in the
    normal case where chromadb imports successfully."""
    assert vector_store_module.chromadb is not None
    assert vector_store_module.CHROMADB_IMPORT_ERROR is None

    store = VectorStore(persist_directory=tmp_path)
    assert store.count() == 0
