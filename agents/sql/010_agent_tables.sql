-- Phase 1 agent-layer tables. Emit only; do not run automatically.
-- DDL is split into separate CREATE TABLE statements on purpose.

CREATE TABLE IF NOT EXISTS scrape_run (
    run_id uuid PRIMARY KEY,
    source_name text NOT NULL,
    entity_type text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('dry_run', 'live')),
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'skipped')),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    stats jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text,
    cost_usd numeric(10, 6) NOT NULL DEFAULT 0,
    config jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS raw_document (
    raw_document_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES scrape_run(run_id) ON DELETE CASCADE,
    url text NOT NULL,
    content_hash text NOT NULL,
    content_type text,
    fetched_at timestamptz NOT NULL,
    content text NOT NULL,
    storage_path text,
    meta jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, url, content_hash)
);

CREATE TABLE IF NOT EXISTS staged_record (
    staged_record_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES scrape_run(run_id) ON DELETE CASCADE,
    raw_document_id uuid REFERENCES raw_document(raw_document_id) ON DELETE SET NULL,
    entity_type text NOT NULL,
    natural_key text NOT NULL,
    source_url text NOT NULL,
    prompt_version text,
    extracted_at timestamptz,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    sector_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
    relevance jsonb NOT NULL DEFAULT '{}'::jsonb,
    route jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'staged',
    target_entity_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, entity_type, natural_key)
);

CREATE TABLE IF NOT EXISTS field_proposal (
    proposal_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES scrape_run(run_id) ON DELETE CASCADE,
    staged_record_id uuid NOT NULL REFERENCES staged_record(staged_record_id) ON DELETE CASCADE,
    source_id uuid NOT NULL REFERENCES source(source_id),
    entity_type text NOT NULL,
    entity_id uuid,
    field_name text NOT NULL,
    proposed_value text,
    current_value text,
    source_url text NOT NULL,
    confidence numeric(5, 4),
    reason text,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'superseded')),
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    decided_by text
);
