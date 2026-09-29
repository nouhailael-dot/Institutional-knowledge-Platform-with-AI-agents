BEGIN;
DROP INDEX IF EXISTS ix_person_discovery_profile_actor_enrichment;
ALTER TABLE person_review_queue
    DROP COLUMN IF EXISTS affiliation_raw;
ALTER TABLE person_discovery_profile
    DROP COLUMN IF EXISTS needs_actor_enrichment,
    DROP COLUMN IF EXISTS affiliation_raw;
COMMIT;
