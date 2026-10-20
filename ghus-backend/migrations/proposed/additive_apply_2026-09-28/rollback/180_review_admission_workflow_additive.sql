BEGIN;
DROP INDEX IF EXISTS ix_search_candidate_review_status;
ALTER TABLE event_review_queue DROP COLUMN IF EXISTS notes;
ALTER TABLE search_candidate
    DROP COLUMN IF EXISTS review_updated_at,
    DROP COLUMN IF EXISTS review_status;
DROP TABLE IF EXISTS review_admission_decision;
DROP TABLE IF EXISTS proposed_hub;
COMMIT;
