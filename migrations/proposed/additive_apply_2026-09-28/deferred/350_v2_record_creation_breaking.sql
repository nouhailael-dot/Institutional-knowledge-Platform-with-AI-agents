-- DEFERRED; NO RUNNER. Must ship with the Phase 3 runtime.
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS review_item_review_kind_check;
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','fact_conflict','pending_human_update','classification',
    'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub',
    'verify_actor'
)) NOT VALID;
