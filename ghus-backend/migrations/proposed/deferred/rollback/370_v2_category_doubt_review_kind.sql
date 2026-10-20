BEGIN;

UPDATE review_item
SET review_kind = 'classification',
    payload = payload || jsonb_build_object(
        'compatibility_bridge', true,
        'canonical_review_kind', 'category_doubt'
    )
WHERE review_kind = 'category_doubt';

ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','fact_conflict','pending_human_update','classification',
    'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub',
    'verify_actor'
)) NOT VALID;

COMMIT;
