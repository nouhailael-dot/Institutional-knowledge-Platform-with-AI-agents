-- ISOLATED TEST DATABASE ONLY.
-- BREAKING / PRODUCTION-DEFERRED: replaces an existing review_item CHECK.
-- This composes the already validated deferred 350, 370, and 390 kind sets so
-- the real Phase 3-7 pipeline can be proven without compatibility pretending.
BEGIN;
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS review_item_review_kind_check;
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','fact_conflict','pending_human_update','classification',
    'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub',
    'verify_actor','category_doubt','hub_needs_review','hub_radius_overlap',
    'hub_member_outside_radius'
)) NOT VALID;
COMMIT;
