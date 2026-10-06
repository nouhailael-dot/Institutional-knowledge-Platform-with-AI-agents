-- DEFERRED FINAL-V2 VALIDATE. Run only after the approved Phase 12 backfill.
BEGIN;

ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_status_v2;
ALTER TABLE actor ADD CONSTRAINT ck_actor_status_v2
    CHECK (status IN ('imported','parked','verified','rejected')) NOT VALID;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_category_complete;
ALTER TABLE actor ADD CONSTRAINT ck_actor_category_complete CHECK (
    nullif(btrim(actor_category),'') IS NOT NULL
    AND nullif(btrim(category_type),'') IS NOT NULL
) NOT VALID;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS fk_actor_category_type;
ALTER TABLE actor ADD CONSTRAINT fk_actor_category_type
    FOREIGN KEY(actor_category,category_type)
    REFERENCES actor_category_type_definition(category_code,type_code) NOT VALID;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_other_type_note;
ALTER TABLE actor ADD CONSTRAINT ck_actor_other_type_note CHECK (
    category_type <> 'other' OR nullif(btrim(category_note),'') IS NOT NULL
) NOT VALID;

ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'verify_actor','category_doubt','geocode_failed','hub_needs_review',
    'hub_radius_overlap','hub_member_outside_radius','hub_center_drift',
    'hub_proposal','possible_duplicate','fact_conflict','pending_update',
    'verify_person','verify_event','identity','affiliation_change'
)) NOT VALID;

ALTER TABLE actor VALIDATE CONSTRAINT ck_actor_status_v2;
ALTER TABLE actor VALIDATE CONSTRAINT ck_actor_category_complete;
ALTER TABLE actor VALIDATE CONSTRAINT fk_actor_category_type;
ALTER TABLE actor VALIDATE CONSTRAINT ck_actor_other_type_note;
ALTER TABLE actor VALIDATE CONSTRAINT ck_actor_coordinates;
ALTER TABLE actor VALIDATE CONSTRAINT fk_actor_source_origin;
ALTER TABLE review_item VALIDATE CONSTRAINT ck_review_item_kind;

-- Hub validation is deliberately delegated to proposal 400 after all 49 hubs
-- and all 821 memberships have topic/center/source evidence backfilled.
COMMIT;
