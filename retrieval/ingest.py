"""
LCD/NCD ingestion from the CMS Coverage API (MCD API).

Fetches Local Coverage Determinations (LCDs) and National Coverage Determinations
(NCDs) from the CMS Medicare Coverage Database REST API. Each document is stored
with its metadata: document_id, title, contractor (for LCDs), effective_date,
end_date, and revision_effective_date.

Also supports ingestion of CMS Coverage Articles (policy articles associated with
LCDs that specify coding guidelines and billing instructions).

Output: raw document records saved to data/reference/coverage/ for versioning,
then passed to chunking.chunk_document() for vector store indexing.

Source: CMS MCD API (https://api.coverage-apis.cms.gov/).
Refresh cadence: run at startup and on-demand when coverage data may be stale.
"""
