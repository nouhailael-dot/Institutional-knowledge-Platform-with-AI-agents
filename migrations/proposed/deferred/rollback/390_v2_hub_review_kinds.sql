BEGIN;

UPDATE review_item
SET review_kind = CASE
        WHEN payload->>'phase6_bridge_previous_kind' = 'same_topic_overlap'
            THEN 'same_topic_overlap'
        ELSE 'hub_assignment'
    END,
    payload = (payload - 'phase6_bridge_migrated' - 'phase6_bridge_previous_kind') || jsonb_build_object(
        'compatibility_bridge', true,
        'canonical_review_kind', review_kind
    )
WHERE review_kind IN (
    'hub_needs_review','hub_radius_overlap','hub_member_outside_radius'
)
  AND COALESCE((payload->>'phase6_bridge_migrated')::boolean, false);

ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','fact_conflict','pending_human_update','classification',
    'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub',
    'verify_actor','category_doubt'
)) NOT VALID;

COMMIT;
