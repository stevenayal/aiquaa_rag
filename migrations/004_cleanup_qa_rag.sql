-- Migration 004: cleanup existing QA RAG content before ISTQB re-index
-- Applied: 2026-06-22
-- Purpose: remove any prior QA/ISTQB documents and chunks so the indexer
--          can start clean. Safe to run even if no rows match.

DELETE FROM rag_chunks
WHERE document_id IN (
  SELECT id FROM rag_documents
  WHERE source IN ('qa', 'istqb', 'istqb_ctfl', 'istqb_performance')
     OR industry = 'qa'
);

DELETE FROM rag_documents
WHERE source IN ('qa', 'istqb', 'istqb_ctfl', 'istqb_performance')
   OR industry = 'qa';
