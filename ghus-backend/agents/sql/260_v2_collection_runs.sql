-- PROPOSAL ONLY. Auditable layer, budget, request, and fetched-document records.
BEGIN;

CREATE TABLE IF NOT EXISTS collection_request (
    collection_request_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    requested_by text NOT NULL,
    request_kind text NOT NULL CHECK (request_kind IN ('mapping','deep_pull','specific_ask','people','events')),
    topic_id uuid REFERENCES topic(topic_id),
    actor_id uuid REFERENCES actor(actor_id),
    need_text text,
    layer smallint NOT NULL CHECK (layer IN (1,2,3)),
    approved boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (request_kind <> 'specific_ask' OR nullif(btrim(need_text),'') IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS collection_run (
    collection_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_request_id uuid NOT NULL REFERENCES collection_request(collection_request_id),
    job_name text NOT NULL,
    dry_run boolean NOT NULL DEFAULT true,
    status text NOT NULL DEFAULT 'running' CHECK (status IN ('running','succeeded','attention','failed')),
    fetch_budget integer NOT NULL CHECK (fetch_budget >= 0),
    fetch_count integer NOT NULL DEFAULT 0 CHECK (fetch_count >= 0),
    max_usd numeric(10,4),
    spent_usd numeric(10,4) NOT NULL DEFAULT 0,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status_reason text,
    CHECK (fetch_count <= fetch_budget),
    CHECK (spent_usd >= 0 AND (max_usd IS NULL OR spent_usd <= max_usd))
);

CREATE TABLE IF NOT EXISTS fetched_document (
    fetched_document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_run_id uuid NOT NULL REFERENCES collection_run(collection_run_id),
    url text NOT NULL,
    canonical_url text NOT NULL,
    content_hash text NOT NULL,
    page_role text NOT NULL CHECK (page_role IN ('homepage','topic','search_result','uploaded','other')),
    source_id uuid NOT NULL REFERENCES source(source_id),
    fetched_at timestamptz NOT NULL,
    UNIQUE (collection_run_id,canonical_url,content_hash)
);

CREATE INDEX IF NOT EXISTS ix_collection_run_request ON collection_run(collection_request_id);
COMMIT;
-- ROLLBACK: export run evidence, then drop fetched_document, collection_run, collection_request.

