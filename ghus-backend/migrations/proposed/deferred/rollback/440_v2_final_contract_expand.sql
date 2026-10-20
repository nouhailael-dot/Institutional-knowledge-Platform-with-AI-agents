BEGIN;
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','verify_actor','category_doubt','classification',
    'geocode_failed','geocode','hub_needs_review','hub_assignment',
    'hub_radius_overlap','same_topic_overlap','hub_member_outside_radius',
    'hub_center_drift','hub_proposal','new_hub','fact_conflict','pending_update',
    'pending_human_update','identity','affiliation_change'
)) NOT VALID;
DROP TRIGGER IF EXISTS actor_verification_event_project_status ON actor_verification_event;
DROP FUNCTION IF EXISTS ghus_project_actor_verification_status();
DROP TRIGGER IF EXISTS actor_verification_event_append_only ON actor_verification_event;
DROP TABLE IF EXISTS actor_verification_event;
ALTER TABLE actor DROP COLUMN IF EXISTS status;
COMMIT;
