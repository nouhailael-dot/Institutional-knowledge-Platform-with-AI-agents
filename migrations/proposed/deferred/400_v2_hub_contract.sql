-- DEFERRED BREAKING PROPOSAL. Phase 12 must backfill controlled topics,
-- coordinates, statuses, sources, and memberships before validation.
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
ALTER TABLE hub ADD CONSTRAINT uq_hub_id_topic UNIQUE (hub_id, topic_id);

ALTER TABLE hub_actor
    ALTER COLUMN topic_id SET NOT NULL,
    ALTER COLUMN assignment_outcome SET NOT NULL,
    ALTER COLUMN outside_radius SET NOT NULL,
    ALTER COLUMN overlap_flag SET NOT NULL,
    ALTER COLUMN source_id SET NOT NULL;
ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS fk_hub_actor_hub_topic;
ALTER TABLE hub_actor ADD CONSTRAINT fk_hub_actor_hub_topic
    FOREIGN KEY (hub_id, topic_id) REFERENCES hub(hub_id, topic_id) NOT VALID;
ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS ck_hub_actor_assignment_outcome;
ALTER TABLE hub_actor ADD CONSTRAINT ck_hub_actor_assignment_outcome CHECK (
    assignment_outcome IN ('assigned','legacy_membership_preserved')
) NOT VALID;

COMMIT;
