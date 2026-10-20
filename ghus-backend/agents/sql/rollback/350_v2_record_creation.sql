BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM review_item WHERE review_kind = 'verify_actor') THEN
        RAISE EXCEPTION 'export and resolve verify_actor rows before rolling back Phase 3';
    END IF;
END $$;
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','fact_conflict','pending_human_update','classification',
    'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub'
)) NOT VALID;
DELETE FROM source_origin_definition
WHERE origin_code IN ('imported_phase1','claude_discovered','ghus_uploaded_doc')
  AND NOT EXISTS (
      SELECT 1 FROM actor WHERE actor.source_origin = source_origin_definition.origin_code
  );
COMMIT;
