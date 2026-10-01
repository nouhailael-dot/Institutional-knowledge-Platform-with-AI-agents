-- PROPOSAL ONLY. Phase 5 metadata on V2-owned reference data.
-- Never execute against the shared database from an agent session.
BEGIN;

ALTER TABLE actor_category_type_definition
    ADD COLUMN IF NOT EXISTS definition text,
    ADD COLUMN IF NOT EXISTS is_other boolean NOT NULL DEFAULT false;

UPDATE actor_category_type_definition
SET definition = COALESCE(
        NULLIF(btrim(definition), ''),
        'Architecture V2 category type: ' || display_name
    ),
    is_other = (type_code = 'other');

ALTER TABLE actor_category_type_definition
    ALTER COLUMN definition SET NOT NULL;

ALTER TABLE actor_category_type_definition
    DROP CONSTRAINT IF EXISTS ck_actor_category_type_other_flag;
ALTER TABLE actor_category_type_definition
    ADD CONSTRAINT ck_actor_category_type_other_flag
    CHECK ((type_code = 'other') = is_other);

CREATE UNIQUE INDEX IF NOT EXISTS ux_actor_category_one_other
    ON actor_category_type_definition(category_code)
    WHERE is_other;

COMMIT;
-- ROLLBACK: agents/sql/rollback/370_v2_actor_classification.sql
