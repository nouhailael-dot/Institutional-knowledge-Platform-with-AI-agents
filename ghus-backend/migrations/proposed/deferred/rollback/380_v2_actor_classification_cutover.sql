BEGIN;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_other_type_note;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS ck_actor_category_complete;
ALTER TABLE actor DROP CONSTRAINT IF EXISTS fk_actor_category_type;
COMMIT;
