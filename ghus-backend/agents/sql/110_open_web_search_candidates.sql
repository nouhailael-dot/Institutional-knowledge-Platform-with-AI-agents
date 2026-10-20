-- Open-web Phase 1 candidate search audit table. Emit only; do not run automatically.

CREATE TABLE IF NOT EXISTS search_candidate (
    candidate_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES scrape_run(run_id) ON DELETE CASCADE,
    entity_type text NOT NULL,
    query text NOT NULL,
    provider text NOT NULL,
    url text NOT NULL,
    title text,
    snippet text,
    domain text NOT NULL,
    triage_verdict text NOT NULL,
    triage_reason text,
    fit_score numeric(4, 3),
    duplicate_of uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE search_candidate
    ADD COLUMN IF NOT EXISTS duplicate_of uuid;

CREATE INDEX IF NOT EXISTS ix_search_candidate_run_entity_score
    ON search_candidate (run_id, entity_type, fit_score DESC);

CREATE INDEX IF NOT EXISTS ix_search_candidate_domain
    ON search_candidate (domain);
