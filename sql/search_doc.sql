-- The RAG index table. Built by embed.py, read by retrieve.py.
-- Kept deliberately separate from the colleague's 21-table schema so his
-- migrations and ours never collide. Run this ONCE in the Supabase SQL editor.

-- 1. Enable pgvector (safe to run repeatedly).
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. The index table: one row per entity, holding the assembled text and its
--    embedding side by side so retrieval never has to re-join the source tables.
CREATE TABLE IF NOT EXISTS search_doc (
  entity_id   uuid PRIMARY KEY,
  entity_type text,              -- 'actor' | 'hub' | 'event'
  name        text,
  doc_text    text,              -- assembled searchable blob (see assemble.py)
  embedding   vector(1024),      -- Voyage voyage-3 -> 1024 dims
  -- Keyword-search vector, auto-derived from doc_text. This is the other half
  -- of hybrid retrieval: it catches literal acronyms (USGS, SRNL, IFAD) that
  -- vector search ranks poorly. STORED = computed on write, no app code needed.
  doc_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(doc_text, ''))) STORED
);

-- 3. Keyword index (GIN over the tsvector).
CREATE INDEX IF NOT EXISTS search_doc_tsv_idx ON search_doc USING gin (doc_tsv);

-- 4. Vector index. At ~300 rows this is OPTIONAL — an exact scan is fast and
--    more accurate. Add it only once the table is populated (ivfflat trains on
--    existing data, so creating it on an empty table is pointless). Uncomment
--    after running embed.py:
--
-- CREATE INDEX IF NOT EXISTS search_doc_embedding_idx
--   ON search_doc USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);
