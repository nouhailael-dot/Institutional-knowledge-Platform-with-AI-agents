-- PROPOSAL ONLY. Never executed against the shared database by an agent.
-- Architecture V2 Phase 4: additive static Census Places coordinate table.
BEGIN;
CREATE TABLE IF NOT EXISTS us_city_coord (
    geoid text PRIMARY KEY,
    state_code text NOT NULL REFERENCES region_state(state_code),
    place_name text NOT NULL,
    normalized_city text NOT NULL,
    latitude numeric(9,6) NOT NULL,
    longitude numeric(9,6) NOT NULL,
    lsad text NOT NULL,
    function_status text NOT NULL,
    gazetteer_year smallint NOT NULL,
    source_url text NOT NULL,
    source_sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (state_code, geoid)
);
CREATE INDEX IF NOT EXISTS ix_us_city_coord_lookup
    ON us_city_coord(state_code, normalized_city);
COMMIT;
