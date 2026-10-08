-- PROPOSAL ONLY. Never executed against the shared database by an agent.
-- Local ghus_v2_*_test databases only. Production DDL needs schema-owner
-- approval, a verified fresh backup, a tested rollback and a coordinated
-- deployment, all outside this change.
--
-- Restore the SECTOR dimension in Architecture V2, so a hub can match an actor
-- on sector with topic as a secondary signal.
--
-- Why this is needed
--   Architecture V2 collapsed sector into topic. The `topic` table was seeded
--   1:1 from the ten legacy sector codes (AGRI, AI, CHEM, CROSS, DIASPORA,
--   ENERGY, HEALTH, MINING, SUSTAIN, WATER), and the V1 tables `sector`,
--   `actor_sector`, `event_sector` and `hub_sector_strength` were not carried
--   forward. The only surviving sector data in V2 is the `hub.primary_sectors`
--   and `hub.secondary_sectors` text arrays.
--
--   That makes two different things one thing. A sector is a broad, stable
--   thematic area an actor works in; a topic is the specific thing a search was
--   run for. Hub membership is a question about the first, not the second.
--
--   It also blocks hub assignment outright today. The Phase 12 dry run records
--   actor_topic_rows = 0 and 965 actors blocked on controlled_topic: no actor
--   carries a sourced topic, so a topic-gated assignment can never fire. The
--   legacy `actor_sector` rows, by contrast, already exist and already carry a
--   source, so a sector-gated assignment has data to work with from day one.
--
-- What this does
--   1. Creates `sector` as a controlled vocabulary, seeded from the same ten
--      codes, with the hierarchy column V1 had.
--   2. Creates `actor_sector` as a sourced many-to-many link, with the same
--      evidence discipline as `actor_topic`: a source is required, and a
--      strength is recorded.
--   3. Creates `event_sector` and `hub_sector` on the same pattern.
--   4. Leaves `topic`, `actor_topic` and `hub.topic_id` exactly as they are.
--      Topic becomes the SECONDARY signal; it is not removed, not renamed and
--      not repurposed.
--
-- What this deliberately does NOT do
--   * It does not backfill a single row. Migrating legacy `actor_sector` into
--     the V2 table is a separate, reviewed data step, because each row needs a
--     V2 `source_id` and the legacy rows' sources must be mapped, not invented.
--   * It does not drop `hub.primary_sectors` / `secondary_sectors`. Those stay
--     until the hub_sector rows are populated and verified.
--   * It does not change the hub detection thresholds. 10 families, 5
--     categories, 50-mile core, 200-mile cluster are unchanged; only the
--     dimension the clustering partitions on moves from topic to sector.
--
-- ORDERING: after agents/sql/190_v2_reference_data.sql. Independent of 510.
-- ROLLBACK: agents/sql/rollback/520_v2_sector_dimension.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. The controlled sector vocabulary.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sector (
    sector_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code             text NOT NULL UNIQUE,
    name             text NOT NULL UNIQUE,
    description      text,
    parent_sector_id uuid REFERENCES sector(sector_id),
    -- A thematic sector is selectable in the Review sector box. CROSS and
    -- DIASPORA are not thematic and are pending a GHUS decision (Appendix H
    -- item 3), so they are seeded inactive rather than guessed at.
    is_thematic      boolean NOT NULL DEFAULT true,
    active           boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_sector_not_own_parent CHECK (parent_sector_id IS DISTINCT FROM sector_id)
);

INSERT INTO sector(code, name, description, is_thematic, active) VALUES
    ('AGRI',     'Agriculture',             'Agriculture, agrifood and agritech', true,  true),
    ('WATER',    'Water',                   'Water resources, treatment and irrigation', true, true),
    ('AI',       'Artificial Intelligence', 'Artificial intelligence and machine learning', true, true),
    ('ENERGY',   'Energy Transition',       'Energy systems and the energy transition', true, true),
    ('MINING',   'Mining',                  'Mining, minerals and critical materials', true, true),
    ('CHEM',     'Specialty Chemicals',     'Chemistry, specialty chemicals and advanced materials', true, true),
    ('HEALTH',   'Healthcare',              'Health, clinical and biomedical', true, true),
    ('SUSTAIN',  'Sustainability',          'Sustainability, climate and earth systems', true, true),
    ('CROSS',    'Cross-Thematic',          'Spans several thematic sectors; pending a GHUS decision', false, false),
    ('DIASPORA', 'African Diaspora',        'Diaspora networks; pending a GHUS decision', false, false)
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. actor_sector. Same evidence discipline as actor_topic: a sector claim
--    needs a source and a reason, and strength is a controlled value.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actor_sector (
    actor_id       uuid NOT NULL REFERENCES actor(actor_id),
    sector_id      uuid NOT NULL REFERENCES sector(sector_id),
    match_strength text NOT NULL CHECK (match_strength IN ('strong', 'moderate')),
    match_reason   text NOT NULL CHECK (char_length(match_reason) BETWEEN 1 AND 1000),
    is_primary     boolean NOT NULL DEFAULT false,
    source_id      uuid NOT NULL REFERENCES source(source_id),
    source_origin  text REFERENCES source_origin_definition(origin_code),
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id, sector_id)
);

CREATE INDEX IF NOT EXISTS ix_actor_sector_sector ON actor_sector(sector_id);
-- At most one primary sector per actor: "which sector is this actor's hub
-- question about" must have exactly one answer when it is asked.
CREATE UNIQUE INDEX IF NOT EXISTS ux_actor_sector_primary
    ON actor_sector(actor_id) WHERE is_primary;

-- ---------------------------------------------------------------------------
-- 3. event_sector and hub_sector, on the same pattern.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_sector (
    event_id   uuid NOT NULL REFERENCES event(event_id),
    sector_id  uuid NOT NULL REFERENCES sector(sector_id),
    source_id  uuid NOT NULL REFERENCES source(source_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, sector_id)
);

CREATE TABLE IF NOT EXISTS hub_sector (
    hub_id     uuid NOT NULL REFERENCES hub(hub_id),
    sector_id  uuid NOT NULL REFERENCES sector(sector_id),
    is_primary boolean NOT NULL DEFAULT false,
    source_id  uuid REFERENCES source(source_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hub_id, sector_id)
);

CREATE INDEX IF NOT EXISTS ix_hub_sector_sector ON hub_sector(sector_id);
-- A hub answers for exactly one primary sector. Secondary sectors are extra
-- rows with is_primary false.
CREATE UNIQUE INDEX IF NOT EXISTS ux_hub_sector_primary
    ON hub_sector(hub_id) WHERE is_primary;

-- ---------------------------------------------------------------------------
-- 4. Append-only guards, matching the discipline of the rest of the ledger.
--    A sector claim is evidence; it is corrected by adding, never by deleting.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ghus_guard_sector_link_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not permitted', TG_TABLE_NAME, TG_OP;
END $$;

DROP TRIGGER IF EXISTS actor_sector_append_only ON actor_sector;
CREATE TRIGGER actor_sector_append_only
    BEFORE UPDATE OR DELETE ON actor_sector
    FOR EACH ROW EXECUTE FUNCTION ghus_guard_sector_link_append_only();

DROP TRIGGER IF EXISTS hub_sector_append_only ON hub_sector;
CREATE TRIGGER hub_sector_append_only
    BEFORE DELETE ON hub_sector
    FOR EACH ROW EXECUTE FUNCTION ghus_guard_sector_link_append_only();

-- ---------------------------------------------------------------------------
-- 5. Post-apply assertions.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    seeded   integer;
    thematic integer;
BEGIN
    SELECT count(*) INTO seeded FROM sector;
    IF seeded <> 10 THEN
        RAISE EXCEPTION 'expected 10 seeded sectors, found %', seeded;
    END IF;
    SELECT count(*) INTO thematic FROM sector WHERE is_thematic AND active;
    IF thematic <> 8 THEN
        RAISE EXCEPTION 'expected 8 selectable thematic sectors, found %', thematic;
    END IF;
    -- The sector codes and the topic codes must stay aligned while both exist,
    -- or a hub's sector and its topic could disagree about what they name.
    IF EXISTS (
        SELECT 1 FROM topic t WHERE NOT EXISTS (
            SELECT 1 FROM sector s WHERE s.code = t.code
        )
    ) THEN
        RAISE EXCEPTION 'a controlled topic has no matching sector code';
    END IF;
END $$;

COMMIT;
