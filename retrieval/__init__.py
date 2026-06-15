"""
Retrieval layer: LCD/NCD ingestion, chunking, and vector store.

Grounds all LLM-generated coverage findings in specific retrieved policy text.
The pipeline is: ingest (download/parse) → chunk → embed → store in ChromaDB.
At query time, the coverage_validation agent retrieves the top-K relevant chunks
for a given dx/procedure pair, and citations are drawn directly from chunk metadata.
"""
