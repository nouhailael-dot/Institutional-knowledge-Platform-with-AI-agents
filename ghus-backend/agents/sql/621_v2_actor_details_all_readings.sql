-- Architecture V2 - actor_details also shows the readings that have no topic.
--
-- Migration 620 filled actor_details from actor_fact_current_pointer, which
-- holds one current reading per organization, topic and box. On the shared
-- database (5 Nov 2026) that gave 42 organizations: 12,429 readings of 963
-- organizations carried over from V1 (focus, technical approach, activities,
-- funding summary, constraints, TRL...) have no topic, so no pointer, and were
-- missing from the table.
--
-- A box's value now comes from the organization's current readings: the
-- pointer's reading for each topic, and the newest accepted reading that has
-- no topic. A found value is preferred to not_found, then the newest wins. A
-- reading under conflict (GHUS's value kept) never shows. New topic-less
-- readings refresh the row as they are written, like pointer changes do.
--
-- ORDERING: after 620. Additive only: replaces one function, adds one trigger.
-- ROLLBACK: agents/sql/rollback/621_v2_actor_details_all_readings.sql
-- Local isolated test databases first. Production needs the platform owner's
-- approval, a fresh backup and a ledger entry.

BEGIN;

CREATE OR REPLACE FUNCTION ghus_actor_details_refresh(p_actor uuid, p_key text)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    v_value jsonb;
    v_source jsonb;
    v_column boolean;
BEGIN
    SELECT CASE WHEN f.collection_state = 'found' THEN f.fact_value
                ELSE to_jsonb(f.collection_state) END,
           jsonb_strip_nulls(jsonb_build_object(
               'source_url', s.url, 'retrieved_at', f.retrieved_at,
               'confidence', f.confidence, 'topic_id', f.topic_id,
               'actor_fact_id', f.actor_fact_id))
      INTO v_value, v_source
      FROM actor_fact f
      LEFT JOIN source s ON s.source_id = f.source_id
     WHERE f.actor_id = p_actor AND f.fact_key = p_key
       AND (EXISTS (SELECT 1 FROM actor_fact_current_pointer p
                     WHERE p.actor_fact_id = f.actor_fact_id)
            OR (f.topic_id IS NULL AND EXISTS (
                    SELECT 1 FROM actor_fact_current c
                     WHERE c.actor_fact_id = f.actor_fact_id
                       AND c.resolution_state = 'accepted')))
     ORDER BY (f.collection_state = 'found') DESC, f.retrieved_at DESC NULLS LAST,
              f.created_at DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO actor_details (actor_id) VALUES (p_actor) ON CONFLICT (actor_id) DO NOTHING;

    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'actor_details'
                      AND column_name = p_key
                      AND column_name NOT IN ('actor_id', 'other_facts', 'fact_sources',
                                              'updated_at'))
      INTO v_column;

    IF v_column THEN
        EXECUTE format(
            'UPDATE actor_details SET %I = $1, fact_sources = fact_sources || $2, '
            'updated_at = now() WHERE actor_id = $3', p_key)
        USING v_value, jsonb_build_object(p_key, v_source), p_actor;
    ELSE
        UPDATE actor_details
           SET other_facts = other_facts || jsonb_build_object(p_key, v_value),
               fact_sources = fact_sources || jsonb_build_object(p_key, v_source),
               updated_at = now()
         WHERE actor_id = p_actor;
    END IF;
END $fn$;

CREATE OR REPLACE FUNCTION ghus_actor_details_on_topicless_fact() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    PERFORM ghus_actor_details_refresh(NEW.actor_id, NEW.fact_key);
    RETURN NULL;
END $fn$;

DROP TRIGGER IF EXISTS actor_details_follows_topicless_fact ON actor_fact;
CREATE TRIGGER actor_details_follows_topicless_fact
    AFTER INSERT ON actor_fact
    FOR EACH ROW WHEN (NEW.topic_id IS NULL)
    EXECUTE FUNCTION ghus_actor_details_on_topicless_fact();

-- Fill it from every reading already recorded.
DO $fill$
DECLARE r record;
BEGIN
    FOR r IN SELECT DISTINCT actor_id, fact_key FROM actor_fact LOOP
        PERFORM ghus_actor_details_refresh(r.actor_id, r.fact_key);
    END LOOP;
END $fill$;

COMMIT;
