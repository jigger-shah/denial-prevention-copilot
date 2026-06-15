"""
ChromaDB vector store interface.

Wraps a persistent local ChromaDB instance (stored at retrieval/chroma_db/) that
holds embedded LCD/NCD chunks. Exposes two primary operations:

  index(chunks): embed and upsert a list of chunk dicts (from chunking.py).
      Uses the chunk's document_id + chunk_index as the ChromaDB document ID to
      support idempotent re-indexing when policy documents are refreshed.

  query(text, n_results, filters): semantic search over the collection.
      Optional metadata filters (e.g. effective_date, document_type) allow
      narrowing retrieval to currently-effective policies.
      Returns a list of (chunk_dict, distance) tuples for the caller to pass
      to the LLM as retrieved context.

Embedding model: defaults to chromadb's built-in embedding function (sentence-
transformers all-MiniLM-L6-v2) for zero-config local use. Can be swapped for
an Anthropic or OpenAI embedding model via environment variable EMBEDDING_PROVIDER.
"""
