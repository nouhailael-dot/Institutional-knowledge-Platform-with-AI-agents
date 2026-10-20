-- DEFERRED BREAKING PROPOSAL. Do not apply from an agent session.
-- Dependency: Phase 12 category/type backfill and Phase 16 legacy-column cutover.
BEGIN;

ALTER TABLE actor DROP CONSTRAINT IF EXISTS fk_actor_category_type;
ALTER TABLE actor ADD CONSTRAINT fk_actor_category_type
    FOREIGN KEY (actor_category, category_type)
    REFERENCES actor_category_type_definition(category_code, type_code)
    NOT VALID;

ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_category_complete;
ALTER TABLE actor ADD CONSTRAINT ck_actor_category_complete CHECK (
    nullif(btrim(actor_category), '') IS NOT NULL
    AND nullif(btrim(category_type), '') IS NOT NULL
) NOT VALID;

ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_other_type_note;
ALTER TABLE actor ADD CONSTRAINT ck_actor_other_type_note CHECK (
    category_type IS DISTINCT FROM 'other'
    OR nullif(btrim(category_note), '') IS NOT NULL
) NOT VALID;

COMMIT;
