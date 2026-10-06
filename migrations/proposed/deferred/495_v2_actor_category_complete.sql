-- PROPOSAL ONLY. Apply only after every unmappable legacy category review has
-- an explicit GHUS resolution. Category type intentionally remains nullable.
BEGIN;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_category_complete;
-- A GHUS-rejected record (e.g. a collection of organizations) has no category.
ALTER TABLE actor ADD CONSTRAINT ck_actor_category_complete
    CHECK (nullif(btrim(actor_category),'') IS NOT NULL OR status = 'rejected') NOT VALID;
ALTER TABLE actor VALIDATE CONSTRAINT ck_actor_category_complete;
COMMIT;
