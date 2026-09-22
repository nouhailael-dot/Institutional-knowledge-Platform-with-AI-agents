-- Preserve extracted affiliation text and flag actor stubs for later enrichment.
-- Emit only; do not run automatically.

ALTER TABLE person_discovery_profile
    ADD COLUMN IF NOT EXISTS affiliation_raw text,
    ADD COLUMN IF NOT EXISTS needs_actor_enrichment boolean NOT NULL DEFAULT false;

ALTER TABLE person_review_queue
    ADD COLUMN IF NOT EXISTS affiliation_raw text;

CREATE INDEX IF NOT EXISTS ix_person_discovery_profile_actor_enrichment
    ON person_discovery_profile (actor_id, created_at)
    WHERE needs_actor_enrichment IS TRUE;
