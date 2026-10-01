BEGIN;
DROP INDEX IF EXISTS ux_actor_category_one_other;
ALTER TABLE actor_category_type_definition
    DROP CONSTRAINT IF EXISTS ck_actor_category_type_other_flag,
    DROP COLUMN IF EXISTS is_other,
    DROP COLUMN IF EXISTS definition;
COMMIT;
