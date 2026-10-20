-- Additive production-drift repair from agents/sql/170.
-- The original NOT NULL DEFAULT on needs_actor_enrichment is deferred.
BEGIN;
ALTER TABLE person_discovery_profile
    ADD COLUMN IF NOT EXISTS affiliation_raw text,
    ADD COLUMN IF NOT EXISTS needs_actor_enrichment boolean;
ALTER TABLE person_review_queue
    ADD COLUMN IF NOT EXISTS affiliation_raw text;
CREATE INDEX IF NOT EXISTS ix_person_discovery_profile_actor_enrichment
    ON person_discovery_profile (actor_id, created_at)
    WHERE needs_actor_enrichment IS TRUE;
COMMIT;
