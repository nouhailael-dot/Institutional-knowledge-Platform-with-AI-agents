-- DEFERRED BREAKING PROPOSAL. Depends on deferred 370 review-kind release.
-- Converts only Phase 6 rows carrying an explicit compatibility marker.
BEGIN;

ALTER TABLE review_item DROP CONSTRAINT IF EXISTS review_item_review_kind_check;
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','fact_conflict','pending_human_update','classification',
    'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub',
    'verify_actor','category_doubt','hub_needs_review','hub_radius_overlap',
    'hub_member_outside_radius'
)) NOT VALID;

UPDATE review_item
SET review_kind = payload->>'canonical_review_kind',
    payload = (payload - 'compatibility_bridge' - 'canonical_review_kind') ||
        jsonb_build_object(
            'phase6_bridge_migrated', true,
            'phase6_bridge_previous_kind', review_kind
        )
WHERE review_kind IN ('hub_assignment','same_topic_overlap')
  AND COALESCE((payload->>'compatibility_bridge')::boolean, false)
  AND payload->>'canonical_review_kind' IN (
      'hub_needs_review','hub_radius_overlap','hub_member_outside_radius'
  );

COMMIT;
