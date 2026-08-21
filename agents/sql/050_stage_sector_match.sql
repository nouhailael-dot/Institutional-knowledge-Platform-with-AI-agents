-- Prompt C: persist sector relevance classification for every staged record.
-- Do not run automatically; this file is emitted for a human migration step.

ALTER TABLE staged_record
    ADD COLUMN IF NOT EXISTS sector_match text NOT NULL DEFAULT 'in_sector';

ALTER TABLE staged_record
    DROP CONSTRAINT IF EXISTS ck_staged_record_sector_match;

ALTER TABLE staged_record
    ADD CONSTRAINT ck_staged_record_sector_match
    CHECK (sector_match IN ('in_sector', 'out_of_sector'));

CREATE INDEX IF NOT EXISTS idx_staged_record_out_of_sector
    ON staged_record (run_id, entity_type, updated_at)
    WHERE status = 'out_of_sector';
