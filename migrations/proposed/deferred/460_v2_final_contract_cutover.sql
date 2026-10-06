-- DEFERRED BREAKING FINAL CUTOVER. Run only after BOTH applications use V2.
BEGIN;

ALTER TABLE actor ALTER COLUMN actor_category SET NOT NULL;
ALTER TABLE actor ALTER COLUMN category_type SET NOT NULL;
ALTER TABLE actor ALTER COLUMN status SET NOT NULL;
ALTER TABLE actor ALTER COLUMN source_origin SET NOT NULL;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='actor' AND column_name='alternate_names')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='actor' AND column_name='alt_names')
  THEN ALTER TABLE actor RENAME COLUMN alternate_names TO alt_names; END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='actor' AND column_name='location_city')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='actor' AND column_name='city')
  THEN ALTER TABLE actor RENAME COLUMN location_city TO city; END IF;
END $$;

DROP VIEW IF EXISTS actor_v1_compat;
DROP VIEW IF EXISTS staged_record_agent3_compat;
DROP VIEW IF EXISTS actor_profile_current;

ALTER TABLE actor
    DROP COLUMN IF EXISTS actor_type,
    DROP COLUMN IF EXISTS actor_type_raw,
    DROP COLUMN IF EXISTS verification_status,
    DROP COLUMN IF EXISTS record_status,
    DROP COLUMN IF EXISTS state;

DROP TABLE IF EXISTS record_verification;
DROP TABLE IF EXISTS organization_hierarchy;
DROP TABLE IF EXISTS actor_profile;
DROP TABLE IF EXISTS actor_capability_fact;

COMMIT;
