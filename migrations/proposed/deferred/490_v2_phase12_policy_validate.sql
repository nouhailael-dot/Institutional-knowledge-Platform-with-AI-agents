-- PROPOSAL ONLY. Supersedes 450 after the corrected Phase 12 backfill.
-- category_type intentionally remains nullable for later AI enrichment.
BEGIN;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_status_v2;
ALTER TABLE actor ADD CONSTRAINT ck_actor_status_v2
    CHECK (status IN ('imported','parked','verified','rejected')) NOT VALID;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_category_complete;
-- Do not add even a NOT VALID completeness check yet: PostgreSQL enforces a
-- new NOT VALID check on subsequent unrelated row updates, which would block
-- status projection for the 214 explicitly unresolved categories. Proposal
-- 495 adds and validates completeness after those reviews are resolved.
ALTER TABLE actor DROP CONSTRAINT IF EXISTS fk_actor_category_type;
ALTER TABLE actor ADD CONSTRAINT fk_actor_category_type
    FOREIGN KEY(actor_category,category_type)
    REFERENCES actor_category_type_definition(category_code,type_code) NOT VALID;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_other_type_note;
ALTER TABLE actor ADD CONSTRAINT ck_actor_other_type_note CHECK (
    category_type IS NULL OR category_type <> 'other'
    OR nullif(btrim(category_note),'') IS NOT NULL
) NOT VALID;

ALTER TABLE actor VALIDATE CONSTRAINT ck_actor_status_v2;
ALTER TABLE actor VALIDATE CONSTRAINT fk_actor_category_type;
ALTER TABLE actor VALIDATE CONSTRAINT ck_actor_other_type_note;
ALTER TABLE actor_verification_event
    VALIDATE CONSTRAINT ck_actor_verification_event_origin;

-- Category completeness remains absent until the reported unmappable legacy
-- categories have explicit GHUS decisions.
COMMIT;
