-- DEFERRED BREAKING PROPOSAL. Do not apply from an agent session.
-- Dependency: the owner-approved review_item CHECK release, including deferred 350.
BEGIN;

ALTER TABLE review_item DROP CONSTRAINT IF EXISTS review_item_review_kind_check;
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','fact_conflict','pending_human_update','classification',
    'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub',
    'verify_actor','category_doubt'
)) NOT VALID;

UPDATE review_item
SET review_kind = 'category_doubt',
    payload = payload - 'compatibility_bridge' - 'canonical_review_kind'
WHERE review_kind = 'classification'
  AND payload->>'issue' = 'category_doubt'
  AND COALESCE((payload->>'compatibility_bridge')::boolean, false);

COMMIT;
