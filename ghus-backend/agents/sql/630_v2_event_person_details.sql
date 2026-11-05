-- Architecture V2 - one row per event and per person with a column for every box.
--
-- Decision (2026-11-05, platform owner): events and people get the same kind
-- of place organizations have in actor_details (migration 620).
--
-- What Review shows about an event or a person beyond the event and person
-- columns is kept as sourced readings in event_fact and person_fact
-- (migration 600: one immutable row per reading, with its source, confidence
-- and date read). Those stay the record of every reading. event_details and
-- person_details hold each record's current value of each box, one column per
-- box, kept up to date by the database itself: whenever a reading is
-- written, its column is refreshed. No code writes them.
--
-- A box read and not found holds "not_found" (standing rule 7). A reading
-- with no column of its own goes to other_facts, so nothing is dropped;
-- fact_sources gives, per box, the page, date read and confidence. An event's
-- stated scale or standing (event_claim) shows in standing_claims, newest
-- first. A person's contact details are never shown here: an "email" reading
-- is left out (people are collected with professional details only).
--
-- Columns from the agents' own box lists: Review's EVENT_FACT_BOXES and
-- PERSON_FACT_BOXES (frontend/review.js), page_facts.py, promote.py's extra
-- fields and the Explore and Map event and person card schemas.
-- The event and person tables themselves are not changed.
-- ORDERING: after 621. Additive only: no existing column or row changes.
-- ROLLBACK: agents/sql/rollback/630_v2_event_person_details.sql
-- Local isolated test databases first. Production needs the platform owner's
-- approval, a fresh backup and a ledger entry.

BEGIN;

-- ---------------------------------------------------------------------------
-- event_details: a column for every event box
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_details (
    event_id uuid PRIMARY KEY REFERENCES event(event_id),
    -- Boxes Review shows for an event
    organizer jsonb,
    format jsonb,
    event_status jsonb,
    registration_url jsonb,
    registration_deadline jsonb,
    speakers jsonb,
    participating_organizations jsonb,
    standing_claims jsonb,
    um6p_ocp_involvement jsonb,
    -- Fields the Data Feed and Explore and Map carry beside them
    event_format jsonb,
    audience jsonb,
    previous_edition jsonb,
    match_explanation jsonb,
    date_status jsonb,
    sector jsonb,
    um6p_ocp_detail jsonb,
    um6p_ocp_source jsonb,
    um6p_ocp_status jsonb,
    -- Anything else read, and where each value comes from
    other_facts jsonb NOT NULL DEFAULT '{}'::jsonb,
    fact_sources jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- person_details: a column for every person box
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS person_details (
    person_id uuid PRIMARY KEY REFERENCES person(person_id),
    -- Boxes Review shows for a person
    department jsonb,
    expertise jsonb,
    relevant_work jsonb,
    work_location jsonb,
    other_affiliations jsonb,
    um6p_ocp_connection jsonb,
    -- Fields Explore and Map's people cards carry beside them
    organization_location jsonb,
    affiliation_evidence_year jsonb,
    work_evidence jsonb,
    criteria_assessment jsonb,
    um6p_ocp_detail jsonb,
    um6p_ocp_source jsonb,
    um6p_ocp_status jsonb,
    -- Anything else read, and where each value comes from
    other_facts jsonb NOT NULL DEFAULT '{}'::jsonb,
    fact_sources jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Refresh one box of one record from its current reading
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ghus_entity_details_refresh(p_kind text, p_id uuid, p_key text)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    v_table text;
    v_id text;
    v_fact_id text;
    v_value jsonb;
    v_source jsonb;
    v_column boolean;
BEGIN
    IF p_kind = 'event' THEN
        v_table := 'event_details'; v_id := 'event_id'; v_fact_id := 'event_fact_id';
    ELSIF p_kind = 'person' THEN
        v_table := 'person_details'; v_id := 'person_id'; v_fact_id := 'person_fact_id';
        IF p_key = 'email' THEN
            RETURN;  -- contact details are never shown
        END IF;
    ELSE
        RAISE EXCEPTION 'unknown record kind %', p_kind;
    END IF;

    EXECUTE format(
        'SELECT CASE WHEN f.collection_state = ''found'' THEN f.fact_value '
        '            ELSE to_jsonb(f.collection_state) END, '
        '       jsonb_strip_nulls(jsonb_build_object(''source_url'', s.url, '
        '           ''retrieved_at'', f.retrieved_at, ''confidence'', f.confidence, '
        '           %L, f.%I)) '
        '  FROM %I f LEFT JOIN source s ON s.source_id = f.source_id '
        ' WHERE f.%I = $1 AND f.fact_key = $2',
        v_fact_id, v_fact_id, p_kind || '_fact_current', v_id)
      INTO v_value, v_source
      USING p_id, p_key;
    IF v_value IS NULL THEN
        RETURN;
    END IF;

    EXECUTE format('INSERT INTO %I (%I) VALUES ($1) ON CONFLICT (%I) DO NOTHING',
                   v_table, v_id, v_id) USING p_id;

    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = v_table
                      AND column_name = p_key
                      AND column_name NOT IN ('event_id', 'person_id', 'other_facts',
                                              'fact_sources', 'updated_at'))
      INTO v_column;

    IF v_column THEN
        EXECUTE format(
            'UPDATE %I SET %I = $1, fact_sources = fact_sources || $2, updated_at = now() '
            'WHERE %I = $3', v_table, p_key, v_id)
        USING v_value, jsonb_build_object(p_key, v_source), p_id;
    ELSE
        EXECUTE format(
            'UPDATE %I SET other_facts = other_facts || $1, '
            'fact_sources = fact_sources || $2, updated_at = now() WHERE %I = $3',
            v_table, v_id)
        USING jsonb_build_object(p_key, v_value), jsonb_build_object(p_key, v_source), p_id;
    END IF;
END $fn$;

-- An event's stated scale or standing, newest first, from event_claim.
CREATE OR REPLACE FUNCTION ghus_event_details_refresh_claims(p_event uuid)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    v_claims jsonb;
    v_source jsonb;
BEGIN
    SELECT jsonb_agg(c.claim_text ORDER BY c.created_at DESC),
           (array_agg(jsonb_strip_nulls(jsonb_build_object(
                'source_url', s.url, 'retrieved_at', c.created_at,
                'event_claim_id', c.event_claim_id)) ORDER BY c.created_at DESC))[1]
      INTO v_claims, v_source
      FROM event_claim c LEFT JOIN source s ON s.source_id = c.source_id
     WHERE c.event_id = p_event;
    IF v_claims IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO event_details (event_id) VALUES (p_event) ON CONFLICT (event_id) DO NOTHING;
    UPDATE event_details
       SET standing_claims = v_claims,
           fact_sources = fact_sources || jsonb_build_object('standing_claims', v_source),
           updated_at = now()
     WHERE event_id = p_event;
END $fn$;

-- ---------------------------------------------------------------------------
-- Follow every new reading
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ghus_event_details_on_fact() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    PERFORM ghus_entity_details_refresh('event', NEW.event_id, NEW.fact_key);
    RETURN NULL;
END $fn$;

CREATE OR REPLACE FUNCTION ghus_person_details_on_fact() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    PERFORM ghus_entity_details_refresh('person', NEW.person_id, NEW.fact_key);
    RETURN NULL;
END $fn$;

CREATE OR REPLACE FUNCTION ghus_event_details_on_claim() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    PERFORM ghus_event_details_refresh_claims(NEW.event_id);
    RETURN NULL;
END $fn$;

DROP TRIGGER IF EXISTS event_details_follows_fact ON event_fact;
CREATE TRIGGER event_details_follows_fact
    AFTER INSERT ON event_fact
    FOR EACH ROW EXECUTE FUNCTION ghus_event_details_on_fact();

DROP TRIGGER IF EXISTS person_details_follows_fact ON person_fact;
CREATE TRIGGER person_details_follows_fact
    AFTER INSERT ON person_fact
    FOR EACH ROW EXECUTE FUNCTION ghus_person_details_on_fact();

DROP TRIGGER IF EXISTS event_details_follows_claim ON event_claim;
CREATE TRIGGER event_details_follows_claim
    AFTER INSERT ON event_claim
    FOR EACH ROW EXECUTE FUNCTION ghus_event_details_on_claim();

-- Fill them from every reading already recorded.
DO $fill$
DECLARE r record;
BEGIN
    FOR r IN SELECT DISTINCT event_id, fact_key FROM event_fact LOOP
        PERFORM ghus_entity_details_refresh('event', r.event_id, r.fact_key);
    END LOOP;
    FOR r IN SELECT DISTINCT person_id, fact_key FROM person_fact LOOP
        PERFORM ghus_entity_details_refresh('person', r.person_id, r.fact_key);
    END LOOP;
    FOR r IN SELECT DISTINCT event_id FROM event_claim LOOP
        PERFORM ghus_event_details_refresh_claims(r.event_id);
    END LOOP;
END $fill$;

COMMIT;
