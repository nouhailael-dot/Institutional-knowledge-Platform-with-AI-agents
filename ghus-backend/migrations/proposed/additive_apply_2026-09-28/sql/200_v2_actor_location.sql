-- PROPOSAL ONLY. Platform-owned actor location evidence.
BEGIN;
CREATE TABLE IF NOT EXISTS actor_location (
    actor_location_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    location_name text,
    country text NOT NULL,
    state_code text REFERENCES region_state(state_code),
    city text NOT NULL,
    region_code text REFERENCES region_definition(region_code),
    latitude numeric(9,6),
    longitude numeric(9,6),
    is_primary boolean NOT NULL DEFAULT false,
    source_id uuid NOT NULL REFERENCES source(source_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((latitude IS NULL) = (longitude IS NULL)),
    UNIQUE (actor_id,country,state_code,city,location_name)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_actor_one_primary_location
    ON actor_location(actor_id) WHERE is_primary;
COMMIT;
