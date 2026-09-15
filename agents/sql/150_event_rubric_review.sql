-- Event rubric evidence and qualification outcomes. Emit only; do not run automatically.

ALTER TABLE search_candidate
    ADD COLUMN IF NOT EXISTS qualification_paths jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE event_review_queue
    ADD COLUMN IF NOT EXISTS review_kind text NOT NULL DEFAULT 'fuzzy_match',
    ADD COLUMN IF NOT EXISTS search_candidate_id uuid,
    ADD COLUMN IF NOT EXISTS rubric jsonb,
    ADD COLUMN IF NOT EXISTS score_breakdown jsonb,
    ADD COLUMN IF NOT EXISTS qualification_paths jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS rerank_position integer,
    ADD COLUMN IF NOT EXISTS rerank_reason text;

ALTER TABLE event_review_queue
    ALTER COLUMN candidate_event_id DROP NOT NULL,
    ALTER COLUMN similarity_score DROP NOT NULL,
    ALTER COLUMN candidate_title DROP NOT NULL,
    ALTER COLUMN shared_start_date DROP NOT NULL;

ALTER TABLE event_review_queue
    DROP CONSTRAINT IF EXISTS ck_event_review_queue_review_kind;

ALTER TABLE event_review_queue
    ADD CONSTRAINT ck_event_review_queue_review_kind
    CHECK (review_kind IN ('fuzzy_match', 'rubric_band'));

CREATE INDEX IF NOT EXISTS ix_event_review_queue_rubric_band
    ON event_review_queue (status, created_at)
    WHERE review_kind = 'rubric_band';
