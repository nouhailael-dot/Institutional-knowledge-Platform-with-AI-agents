BEGIN;
ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS ck_hub_actor_assignment_outcome;
ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS fk_hub_actor_hub_topic;
ALTER TABLE hub_actor
    ALTER COLUMN source_id DROP NOT NULL,
    ALTER COLUMN overlap_flag DROP NOT NULL,
    ALTER COLUMN outside_radius DROP NOT NULL,
    ALTER COLUMN assignment_outcome DROP NOT NULL,
    ALTER COLUMN topic_id DROP NOT NULL;
ALTER TABLE hub DROP CONSTRAINT IF EXISTS uq_hub_id_topic;
ALTER TABLE hub DROP CONSTRAINT IF EXISTS ck_hub_v2_radius;
ALTER TABLE hub DROP CONSTRAINT IF EXISTS ck_hub_v2_center_pair;
ALTER TABLE hub
    ALTER COLUMN center_computed_at DROP NOT NULL,
    ALTER COLUMN center_method_version DROP NOT NULL,
    ALTER COLUMN center_method DROP NOT NULL,
    ALTER COLUMN center_frozen DROP NOT NULL,
    ALTER COLUMN radius_miles DROP NOT NULL,
    ALTER COLUMN center_longitude DROP NOT NULL,
    ALTER COLUMN center_latitude DROP NOT NULL,
    ALTER COLUMN topic_id DROP NOT NULL;
COMMIT;
