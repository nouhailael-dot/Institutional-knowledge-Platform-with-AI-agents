-- PROPOSAL ONLY. Never executed against the shared database by an agent.
-- Local ghus_v2_*_test databases only. Production DDL needs schema-owner
-- approval, a verified fresh backup, a tested rollback and a coordinated
-- deployment, all outside this change.
--
-- Bring the SECTOR dimension into Architecture V2, so a hub can match an actor
-- on sector with topic as a secondary signal (GHUS decision, 2026-10-08).
--
-- What is actually there
--   The V1 tables SURVIVED the migration into the production copy. Verified
--   against ghus_v2_phase12_full_test on 2026-10-08:
--
--     sector               10 rows   AGRI AI CHEM CROSS DIASPORA ENERGY
--                                    HEALTH MINING SUSTAIN WATER
--     actor_sector          0 rows   <- empty
--     event_sector         87 rows
--     hub_sector_strength   0 rows
--     hub.primary_sectors  48 of 48 hubs have one
--     staged_record.sector_codes   6,407 of 7,286 staged records carry codes
--
--   So this migration ADOPTS what exists rather than creating it. It adds the
--   V2 evidence columns the links were missing, and adds hub_sector, which V1
--   never had as a link table.
--
--   What the V2 target schema dropped was these tables' presence in the target
--   manifest, not the data. Architecture V2 Sept needs them: "a real parent
--   when one exists, or through sector, geography, and hub when it doesn't"
--   (1), "the sector(s) this actor fits, and the specific topic it was found
--   for" (5.1), and Case 2 in 6.
--
-- An honest note about coverage
--   actor_sector is EMPTY. No canonical actor carries a sector today, exactly
--   as no canonical actor carries a controlled topic (actor_topic is also 0).
--   Sector-based assignment is therefore NOT ready the moment this migration
--   runs. What it has that topic does not:
--     * every one of the 48 hubs already has a primary sector, so the hub side
--       of the test is answerable now;
--     * 6,407 staged records carry sector codes, so newly promoted actors get
--       a sector immediately;
--     * 574 of the 965 existing actors sit in at least one hub, of which 540
--       resolve to exactly one sector through that membership.
--   That last one is a DERIVATION, not evidence. It is deliberately not done
--   here. See the "backfill" note at the end.
--
-- ORDERING: after agents/sql/190_v2_reference_data.sql. Independent of 510.
-- ROLLBACK: agents/sql/rollback/520_v2_sector_dimension.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. The controlled sector vocabulary. Created when absent, adopted when not.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sector (
    sector_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code             text NOT NULL UNIQUE,
    name             text NOT NULL UNIQUE,
    description      text,
    parent_sector_id uuid REFERENCES sector(sector_id),
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- A thematic sector is selectable in the Review sector box. CROSS and DIASPORA
-- are not thematic and are pending a GHUS decision (brief Appendix H item 3),
-- so they are marked inactive rather than guessed at.
ALTER TABLE sector
    ADD COLUMN IF NOT EXISTS is_thematic boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS active      boolean NOT NULL DEFAULT true;

-- V1 generated sector_id in Python, so the surviving column has no default.
-- Without one, every insert below would have to supply a uuid by hand.
ALTER TABLE sector ALTER COLUMN sector_id SET DEFAULT gen_random_uuid();

INSERT INTO sector(code, name, description) VALUES
    ('AGRI',     'Agriculture',             'Agriculture, agrifood and agritech'),
    ('WATER',    'Water',                   'Water resources, treatment and irrigation'),
    ('AI',       'Artificial Intelligence', 'Artificial intelligence and machine learning'),
    ('ENERGY',   'Energy Transition',       'Energy systems and the energy transition'),
    ('MINING',   'Mining',                  'Mining, minerals and critical materials'),
    ('CHEM',     'Specialty Chemicals',     'Chemistry, specialty chemicals and advanced materials'),
    ('HEALTH',   'Healthcare',              'Health, clinical and biomedical'),
    ('SUSTAIN',  'Sustainability',          'Sustainability, climate and earth systems'),
    ('CROSS',    'Cross-Thematic',          'Spans several thematic sectors; pending a GHUS decision'),
    ('DIASPORA', 'African Diaspora',        'Diaspora networks; pending a GHUS decision')
ON CONFLICT (code) DO NOTHING;

UPDATE sector SET is_thematic = false, active = false
WHERE code IN ('CROSS', 'DIASPORA');

-- ---------------------------------------------------------------------------
-- 2. actor_sector. The V1 table exists and is empty, so the V2 evidence columns
--    can be added NOT NULL without stranding a single row.
--
--    Same discipline as actor_topic: a sector claim needs a source and a
--    reason, and strength is a controlled value.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actor_sector (
    actor_id   uuid NOT NULL REFERENCES actor(actor_id),
    sector_id  uuid NOT NULL REFERENCES sector(sector_id),
    confidence numeric(3,2),
    source_id  uuid REFERENCES source(source_id),
    PRIMARY KEY (actor_id, sector_id)
);

DO $$
DECLARE existing integer;
BEGIN
    SELECT count(*) INTO existing FROM actor_sector;
    IF existing <> 0 THEN
        RAISE EXCEPTION
            'actor_sector holds % row(s). Adding NOT NULL evidence columns would '
            'invent values for them. Migrate those rows deliberately first.',
            existing;
    END IF;
END $$;

ALTER TABLE actor_sector
    ADD COLUMN IF NOT EXISTS match_strength text,
    ADD COLUMN IF NOT EXISTS match_reason   text,
    ADD COLUMN IF NOT EXISTS is_primary     boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS source_origin  text REFERENCES source_origin_definition(origin_code),
    ADD COLUMN IF NOT EXISTS created_at     timestamptz NOT NULL DEFAULT now();

ALTER TABLE actor_sector
    ALTER COLUMN match_strength SET NOT NULL,
    ALTER COLUMN match_reason   SET NOT NULL,
    ALTER COLUMN source_id      SET NOT NULL;

ALTER TABLE actor_sector DROP CONSTRAINT IF EXISTS ck_actor_sector_strength;
ALTER TABLE actor_sector
    ADD CONSTRAINT ck_actor_sector_strength
    CHECK (match_strength IN ('strong', 'moderate'));

ALTER TABLE actor_sector DROP CONSTRAINT IF EXISTS ck_actor_sector_reason;
ALTER TABLE actor_sector
    ADD CONSTRAINT ck_actor_sector_reason
    CHECK (char_length(match_reason) BETWEEN 1 AND 1000);

CREATE INDEX IF NOT EXISTS ix_actor_sector_sector ON actor_sector(sector_id);
-- At most one primary sector per actor: "which sector is this actor's hub
-- question about" must have exactly one answer when it is asked.
CREATE UNIQUE INDEX IF NOT EXISTS ux_actor_sector_primary
    ON actor_sector(actor_id) WHERE is_primary;

-- ---------------------------------------------------------------------------
-- 3. event_sector already holds 87 rows, so its new columns stay NULLABLE.
--    Backfilling a source for a row that never had one would be inventing it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_sector (
    event_id  uuid NOT NULL REFERENCES event(event_id),
    sector_id uuid NOT NULL REFERENCES sector(sector_id),
    PRIMARY KEY (event_id, sector_id)
);

ALTER TABLE event_sector
    ADD COLUMN IF NOT EXISTS source_id  uuid REFERENCES source(source_id),
    ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

-- ---------------------------------------------------------------------------
-- 4. hub_sector is genuinely new: V1 had hub.primary_sectors as a text array
--    and hub_sector_strength as a computed cache, but no link table.
--
--    The array is seeded across from the 48 hubs that have one, because that
--    IS the hub's own recorded sector rather than a derivation about it.
--    hub.primary_sectors is left in place and is not dropped.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hub_sector (
    hub_id     uuid NOT NULL REFERENCES hub(hub_id),
    sector_id  uuid NOT NULL REFERENCES sector(sector_id),
    is_primary boolean NOT NULL DEFAULT false,
    source     text NOT NULL DEFAULT 'hub.primary_sectors',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hub_id, sector_id)
);

INSERT INTO hub_sector(hub_id, sector_id, is_primary, source)
SELECT h.hub_id, s.sector_id, true, 'hub.primary_sectors'
FROM hub h
JOIN LATERAL (SELECT h.primary_sectors[1] AS code) first ON true
JOIN sector s ON s.code = first.code
WHERE h.primary_sectors IS NOT NULL AND cardinality(h.primary_sectors) > 0
ON CONFLICT (hub_id, sector_id) DO NOTHING;

INSERT INTO hub_sector(hub_id, sector_id, is_primary, source)
SELECT h.hub_id, s.sector_id, false, 'hub.secondary_sectors'
FROM hub h
CROSS JOIN LATERAL unnest(COALESCE(h.secondary_sectors, ARRAY[]::text[])) AS sec(code)
JOIN sector s ON s.code = sec.code
ON CONFLICT (hub_id, sector_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS ix_hub_sector_sector ON hub_sector(sector_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_hub_sector_primary
    ON hub_sector(hub_id) WHERE is_primary;

-- ---------------------------------------------------------------------------
-- 5. Append-only guard on the actor link, matching the rest of the ledger.
--    A sector claim is evidence; it is corrected by adding, never by deleting.
--    hub_sector is seeded from an array that may legitimately be recomputed, so
--    it is guarded against DELETE only.
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

DROP TRIGGER IF EXISTS hub_sector_no_delete ON hub_sector;
CREATE TRIGGER hub_sector_no_delete
    BEFORE DELETE ON hub_sector
    FOR EACH ROW EXECUTE FUNCTION ghus_guard_sector_link_append_only();

-- ---------------------------------------------------------------------------
-- 6. Post-apply assertions.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    seeded     integer;
    thematic   integer;
    hubs_total integer;
    hubs_with  integer;
BEGIN
    SELECT count(*) INTO seeded FROM sector;
    IF seeded <> 10 THEN
        RAISE EXCEPTION 'expected 10 seeded sectors, found %', seeded;
    END IF;
    SELECT count(*) INTO thematic FROM sector WHERE is_thematic AND active;
    IF thematic <> 8 THEN
        RAISE EXCEPTION 'expected 8 selectable thematic sectors, found %', thematic;
    END IF;
    -- Every hub that records a primary sector must now have a hub_sector row,
    -- or the hub side of Test 1 is unanswerable for it.
    SELECT count(*) INTO hubs_total FROM hub
    WHERE primary_sectors IS NOT NULL AND cardinality(primary_sectors) > 0;
    SELECT count(*) INTO hubs_with FROM hub h
    WHERE EXISTS (SELECT 1 FROM hub_sector hs WHERE hs.hub_id = h.hub_id AND hs.is_primary);
    IF hubs_with < hubs_total THEN
        RAISE EXCEPTION
            '% hub(s) record a primary sector but have no hub_sector row',
            hubs_total - hubs_with;
    END IF;
    -- The sector codes and the topic codes stay aligned while both exist, or a
    -- hub's sector and its topic could disagree about what they name.
    IF EXISTS (
        SELECT 1 FROM topic t WHERE NOT EXISTS (SELECT 1 FROM sector s WHERE s.code = t.code)
    ) THEN
        RAISE EXCEPTION 'a controlled topic has no matching sector code';
    END IF;
END $$;

COMMIT;

-- BACKFILL, deliberately not done here
--   actor_sector stays empty. Two candidate sources, neither applied:
--
--   1. staged_record.sector_codes (6,407 records). These are evidence and carry
--      their own provenance. New actors get their sectors through the normal
--      promote path, which agents/discovery/promote.py already does.
--
--   2. Hub membership. 574 of 965 existing actors sit in a hub, and 540 of
--      those resolve to exactly one sector through it. That is a DERIVATION
--      about an actor, not evidence from a source about it, and Architecture V2
--      forbids inventing a value. If GHUS wants it, it should run as an
--      explicit, reviewed step that records source_origin and a match_reason
--      naming the hub it came from, and it should raise a review item rather
--      than claim 'strong'. The remaining 391 actors have no derivable sector
--      at all and need real evidence.
