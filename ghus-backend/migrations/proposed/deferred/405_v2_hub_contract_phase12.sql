-- DEFERRED BREAKING PROPOSAL. Supersedes 400 without editing it (Phase 12 data).
-- Identical to 400 except two honest exceptions for legacy GHUS memberships,
-- which were curated without a recorded source and partly without coordinates:
--   * hub_actor.source_id may be NULL only when assignment_outcome is
--     'legacy_membership_preserved' (inventing a source is not allowed);
--   * hub_actor.outside_radius may be NULL only when distance_miles is NULL
--     (the member has no coordinates, so the answer is unknown).
-- Every new assignment still needs a source, a distance and an outcome.
BEGIN;

ALTER TABLE hub
    ALTER COLUMN topic_id SET NOT NULL,
    ALTER COLUMN center_latitude SET NOT NULL,
    ALTER COLUMN center_longitude SET NOT NULL,
    ALTER COLUMN radius_miles SET NOT NULL,
    ALTER COLUMN center_frozen SET NOT NULL,
    ALTER COLUMN center_method SET NOT NULL,
    ALTER COLUMN center_method_version SET NOT NULL,
    ALTER COLUMN center_computed_at SET NOT NULL;

ALTER TABLE hub DROP CONSTRAINT IF EXISTS ck_hub_v2_center_pair;
ALTER TABLE hub ADD CONSTRAINT ck_hub_v2_center_pair CHECK (
    center_latitude BETWEEN -90 AND 90 AND center_longitude BETWEEN -180 AND 180
) NOT VALID;
ALTER TABLE hub DROP CONSTRAINT IF EXISTS ck_hub_v2_radius;
ALTER TABLE hub ADD CONSTRAINT ck_hub_v2_radius CHECK (radius_miles > 0) NOT VALID;
ALTER TABLE hub DROP CONSTRAINT IF EXISTS uq_hub_id_topic;
ALTER TABLE hub ADD CONSTRAINT uq_hub_id_topic UNIQUE (hub_id, topic_id);

ALTER TABLE hub_actor
    ALTER COLUMN topic_id SET NOT NULL,
    ALTER COLUMN assignment_outcome SET NOT NULL,
    ALTER COLUMN overlap_flag SET NOT NULL;
ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS fk_hub_actor_hub_topic;
ALTER TABLE hub_actor ADD CONSTRAINT fk_hub_actor_hub_topic
    FOREIGN KEY (hub_id, topic_id) REFERENCES hub(hub_id, topic_id) NOT VALID;
ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS ck_hub_actor_assignment_outcome;
ALTER TABLE hub_actor ADD CONSTRAINT ck_hub_actor_assignment_outcome CHECK (
    assignment_outcome IN ('assigned','legacy_membership_preserved')
) NOT VALID;
ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS ck_hub_actor_source_or_legacy;
ALTER TABLE hub_actor ADD CONSTRAINT ck_hub_actor_source_or_legacy CHECK (
    source_id IS NOT NULL OR assignment_outcome = 'legacy_membership_preserved'
) NOT VALID;
ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS ck_hub_actor_radius_known;
ALTER TABLE hub_actor ADD CONSTRAINT ck_hub_actor_radius_known CHECK (
    (outside_radius IS NULL) = (distance_miles IS NULL)
) NOT VALID;

ALTER TABLE hub VALIDATE CONSTRAINT ck_hub_v2_center_pair;
ALTER TABLE hub VALIDATE CONSTRAINT ck_hub_v2_radius;
ALTER TABLE hub_actor VALIDATE CONSTRAINT fk_hub_actor_hub_topic;
ALTER TABLE hub_actor VALIDATE CONSTRAINT ck_hub_actor_assignment_outcome;
ALTER TABLE hub_actor VALIDATE CONSTRAINT ck_hub_actor_source_or_legacy;
ALTER TABLE hub_actor VALIDATE CONSTRAINT ck_hub_actor_radius_known;

COMMIT;
