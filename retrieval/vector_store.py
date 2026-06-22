"""
ChromaDB vector store interface.

Wraps a persistent local ChromaDB collection that holds embedded LCD/NCD chunks
(as produced by retrieval/chunking.py:chunk_document()). Exposes two primary
operations on the VectorStore class:

  index(chunks): embed and upsert a list of chunk dicts. Uses the chunk's
      document_id + chunk_index as the ChromaDB document ID, so re-indexing
      the same document is idempotent (upsert overwrites, never duplicates).

  query(text, n_results, filters): semantic search over the collection.
      Optional metadata filters (ChromaDB "where" clause, e.g.
      {"document_id": "LCD_12345"}) narrow retrieval to a specific document
      or policy type. Returns a list of plain dicts — never ChromaDB's native
      QueryResult structure — so callers (agents/coverage_validation.py) don't
      need to know anything about ChromaDB's response shape. Each dict carries
      document_id, document_title, section_heading, effective_date, chunk_index,
      text, and distance — the fields needed to construct a Finding.citation
      (rules/models.py:Citation) without a second lookup.

A VectorStore is constructed against a specific persist_directory rather than
a module-level singleton, so production code and tests (using tmp_path) can
each get a fully isolated ChromaDB instance with no shared state.

Embedding model: ChromaDB's default built-in embedding function
(sentence-transformers all-MiniLM-L6-v2) for zero-config local use.

chromadb is imported defensively (broad except, not just ImportError) because
its import chain has been observed to fail with TypeError on some hosted
runtimes (chromadb -> opentelemetry -> a protobuf version mismatch raising
TypeError deep in a generated _pb2 module, not an ImportError). This module
must stay importable either way, since agents/coverage_validation.py and
agents/coding_validation.py import VectorStore at module load time, ahead of
any retrieval logic — if that import raised, the whole app would fail to
start before reaching the existing vector-store-then-JSON-fallback retrieval
path (agents already catch construction failures there and fall back to the
JSON policy corpus; see _retrieve_from_vector_store() in both agent modules).
"""

try:
    import chromadb
    CHROMADB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # noqa: BLE001 - intentionally broad, see module docstring
    chromadb = None
    CHROMADB_IMPORT_ERROR = exc

DEFAULT_COLLECTION_NAME = "coverage_policies"


class VectorStore:
    """A persistent ChromaDB-backed store of embedded LCD/NCD policy chunks."""

    def __init__(self, persist_directory, collection_name: str = DEFAULT_COLLECTION_NAME):
        if chromadb is None:
            raise RuntimeError(
                "ChromaDB unavailable; falling back to JSON policy corpus"
            ) from CHROMADB_IMPORT_ERROR
        self._client = chromadb.PersistentClient(path=str(persist_directory))
        self._collection = self._client.get_or_create_collection(collection_name)

    def index(self, chunks: list[dict]) -> int:
        """
        Embed and upsert chunk dicts (as produced by chunking.chunk_document()).

        Re-running index() with the same chunks (same document_id + chunk_index)
        overwrites the existing entries rather than creating duplicates.

        Returns the number of chunks indexed. A no-op (returns 0) if chunks is empty.
        """
        if not chunks:
            return 0

        ids = [_chunk_id(chunk) for chunk in chunks]
        documents = [chunk["text"] for chunk in chunks]
        metadatas = [
            {
                "document_id": chunk["document_id"],
                "document_title": chunk.get("document_title", ""),
                "section_heading": chunk.get("section_heading", ""),
                "effective_date": chunk.get("effective_date"),
                "chunk_index": chunk["chunk_index"],
            }
            for chunk in chunks
        ]
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(ids)

    def query(self, text: str, n_results: int = 5, filters: dict | None = None) -> list[dict]:
        """
        Semantic search over the indexed chunks.

        Returns a list of plain dicts (document_id, document_title, section_heading,
        effective_date, chunk_index, text, distance), ordered by relevance.
        Returns [] if the collection is empty — never raises on an empty index.
        """
        available = self._collection.count()
        if available == 0:
            return []

        raw = self._collection.query(
            query_texts=[text],
            n_results=min(n_results, available),
            where=filters,
        )
        return _format_query_result(raw)

    def count(self) -> int:
        """Number of chunks currently indexed."""
        return self._collection.count()


def _chunk_id(chunk: dict) -> str:
    return f"{chunk['document_id']}::{chunk['chunk_index']}"


def _format_query_result(raw: dict) -> list[dict]:
    """Flatten ChromaDB's batched QueryResult (lists-of-lists, one query) into plain dicts."""
    ids = raw["ids"][0]
    documents = raw["documents"][0]
    metadatas = raw["metadatas"][0]
    distances = raw["distances"][0]

    results = []
    for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
        results.append({
            "document_id": metadata.get("document_id"),
            "document_title": metadata.get("document_title"),
            "section_heading": metadata.get("section_heading"),
            "effective_date": metadata.get("effective_date"),
            "chunk_index": metadata.get("chunk_index"),
            "text": document,
            "distance": distance,
        })
    return results
