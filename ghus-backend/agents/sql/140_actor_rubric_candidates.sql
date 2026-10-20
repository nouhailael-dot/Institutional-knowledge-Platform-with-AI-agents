-- Actor gate/rubric/rerank evidence for open-web candidates. Emit only; do not run automatically.

ALTER TABLE search_candidate
    ADD COLUMN IF NOT EXISTS gate_fetch boolean,
    ADD COLUMN IF NOT EXISTS page_fetched boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS rubric jsonb,
    ADD COLUMN IF NOT EXISTS record_preview jsonb,
    ADD COLUMN IF NOT EXISTS score_breakdown jsonb,
    ADD COLUMN IF NOT EXISTS existing_actor_count integer,
    ADD COLUMN IF NOT EXISTS distinctiveness numeric(8, 6),
    ADD COLUMN IF NOT EXISTS score_band text,
    ADD COLUMN IF NOT EXISTS rerank_position integer,
    ADD COLUMN IF NOT EXISTS rerank_reason text;

ALTER TABLE search_candidate
    DROP CONSTRAINT IF EXISTS ck_search_candidate_score_band;

ALTER TABLE search_candidate
    ADD CONSTRAINT ck_search_candidate_score_band
    CHECK (score_band IS NULL OR score_band IN (
        'auto_high', 'review', 'auto_low', 'analysis_failed'
    ));

CREATE INDEX IF NOT EXISTS ix_search_candidate_actor_band_rank
    ON search_candidate (run_id, entity_type, score_band, rerank_position)
    WHERE entity_type = 'actor';
