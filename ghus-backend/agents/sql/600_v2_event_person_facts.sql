-- Architecture V2 - every fact Review shows about an event or a person has a home.
--
-- Decision (2026-11-04, platform owner): everything Review Results shows must
-- be stored when the record is verified - Explore and Map results included,
-- which reach the database through the Data Feed. Organizations already keep
-- every box as a sourced fact (actor_fact). Events and people had only fixed
-- columns, so a format, an audience, a previous edition, a UM6P/OCP
-- involvement, a department, relevant work or other affiliations were shown
-- to the reviewer and lost at admission.
--
-- These two ledgers follow actor_fact (agents/sql/240_v2_fact_ledger.sql):
-- one immutable row per reading, with its source, origin, confidence and date
-- read ("sources and confidence for every fact", Architecture V2 section 5.1);
-- a new value supersedes, nothing is updated or deleted ("never overwrite,
-- never delete", section 6). The *_current views give one current row per key.
-- Standing claims about an event's scale (section 5.4) use the existing
-- event_claim table.
--
-- Written only by agents.enrichment.decisions.append_entity_fact.
-- ORDERING: after 597. Additive only: no existing column or row changes.
-- ROLLBACK: agents/sql/rollback/600_v2_event_person_facts.sql
-- Local isolated test databases first. Production needs the platform owner's
-- approval, a fresh backup and a ledger entry.

BEGIN;

CREATE TABLE IF NOT EXISTS event_fact (
    event_fact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL REFERENCES event(event_id),
    fact_key text NOT NULL CHECK (char_length(fact_key) BETWEEN 1 AND 80),
    fact_value jsonb,
    collection_state text NOT NULL DEFAULT 'found' CHECK (
        collection_state IN ('found','not_found','not_yet_collected')),
    source_id uuid NOT NULL REFERENCES source(source_id),
    source_origin text NOT NULL REFERENCES source_origin_definition(origin_code),
    confidence text NOT NULL CHECK (confidence IN ('high','medium','low')),
    retrieved_at timestamptz NOT NULL,
    generated_by text NOT NULL,
    supersedes_fact_id uuid REFERENCES event_fact(event_fact_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((collection_state = 'found' AND fact_value IS NOT NULL)
           OR (collection_state <> 'found' AND fact_value IS NULL))
);

CREATE TABLE IF NOT EXISTS person_fact (
    person_fact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES person(person_id),
    fact_key text NOT NULL CHECK (char_length(fact_key) BETWEEN 1 AND 80),
    fact_value jsonb,
    collection_state text NOT NULL DEFAULT 'found' CHECK (
        collection_state IN ('found','not_found','not_yet_collected')),
    source_id uuid NOT NULL REFERENCES source(source_id),
    source_origin text NOT NULL REFERENCES source_origin_definition(origin_code),
    confidence text NOT NULL CHECK (confidence IN ('high','medium','low')),
    retrieved_at timestamptz NOT NULL,
    generated_by text NOT NULL,
    supersedes_fact_id uuid REFERENCES person_fact(person_fact_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((collection_state = 'found' AND fact_value IS NOT NULL)
           OR (collection_state <> 'found' AND fact_value IS NULL))
);

CREATE INDEX IF NOT EXISTS ix_event_fact_lookup ON event_fact(event_id, fact_key, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_person_fact_lookup ON person_fact(person_id, fact_key, created_at DESC);

DROP TRIGGER IF EXISTS event_fact_append_only ON event_fact;
CREATE TRIGGER event_fact_append_only BEFORE UPDATE OR DELETE ON event_fact
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
DROP TRIGGER IF EXISTS person_fact_append_only ON person_fact;
CREATE TRIGGER person_fact_append_only BEFORE UPDATE OR DELETE ON person_fact
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

-- The current value of each key: the latest reading that nothing superseded.
CREATE OR REPLACE VIEW event_fact_current AS
SELECT DISTINCT ON (f.event_id, f.fact_key) f.*
FROM event_fact f
WHERE NOT EXISTS (SELECT 1 FROM event_fact s WHERE s.supersedes_fact_id = f.event_fact_id)
ORDER BY f.event_id, f.fact_key, f.created_at DESC, f.event_fact_id DESC;

CREATE OR REPLACE VIEW person_fact_current AS
SELECT DISTINCT ON (f.person_id, f.fact_key) f.*
FROM person_fact f
WHERE NOT EXISTS (SELECT 1 FROM person_fact s WHERE s.supersedes_fact_id = f.person_fact_id)
ORDER BY f.person_id, f.fact_key, f.created_at DESC, f.person_fact_id DESC;

COMMIT;
