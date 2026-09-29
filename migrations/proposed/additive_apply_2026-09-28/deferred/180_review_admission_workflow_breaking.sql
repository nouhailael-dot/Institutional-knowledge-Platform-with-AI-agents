-- DEFERRED; NO RUNNER. Review caller deployment and backfill required.
UPDATE search_candidate SET review_status = 'pending' WHERE review_status IS NULL;
ALTER TABLE search_candidate
    ALTER COLUMN review_status SET DEFAULT 'pending',
    ALTER COLUMN review_status SET NOT NULL;
ALTER TABLE search_candidate DROP CONSTRAINT IF EXISTS search_candidate_review_status_check;
ALTER TABLE search_candidate ADD CONSTRAINT search_candidate_review_status_check
    CHECK (review_status IN ('pending','approved','rejected','deferred','superseded')) NOT VALID;
ALTER TABLE event_review_queue DROP CONSTRAINT IF EXISTS event_review_queue_status_check;
ALTER TABLE event_review_queue ADD CONSTRAINT event_review_queue_status_check
    CHECK (status IN ('pending','approved','rejected','deferred','superseded')) NOT VALID;
ALTER TABLE person_review_queue DROP CONSTRAINT IF EXISTS person_review_queue_status_check;
ALTER TABLE person_review_queue ADD CONSTRAINT person_review_queue_status_check
    CHECK (status IN ('pending','approved','rejected','deferred','superseded')) NOT VALID;
