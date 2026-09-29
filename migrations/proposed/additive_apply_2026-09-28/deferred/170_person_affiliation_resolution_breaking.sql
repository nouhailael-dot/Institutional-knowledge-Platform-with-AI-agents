-- DEFERRED; NO RUNNER. P14 -> P12.
UPDATE person_discovery_profile
SET needs_actor_enrichment = false
WHERE needs_actor_enrichment IS NULL;
ALTER TABLE person_discovery_profile
    ALTER COLUMN needs_actor_enrichment SET DEFAULT false,
    ALTER COLUMN needs_actor_enrichment SET NOT NULL;
