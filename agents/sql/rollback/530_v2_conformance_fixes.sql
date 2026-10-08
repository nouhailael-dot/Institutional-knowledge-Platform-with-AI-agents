-- ROLLBACK for agents/sql/530_v2_conformance_fixes.sql.
-- Local ghus_v2_*_test databases only.
--
-- Drops the guards and the columns this migration added. It refuses to drop a
-- table that already holds rows, because those rows are sourced evidence.
--
-- Note on fk_actor_category_type: 530 adds it only when absent, and the
-- deferred cutover chain (380, 450, 490) also owns it. This rollback does NOT
-- drop it. Removing a constraint that another migration may legitimately have
-- created would silently weaken the schema; drop it deliberately if that is
-- really what is wanted.

BEGIN;

DO $$
DECLARE held integer;
BEGIN
    SELECT (SELECT count(*) FROM strategic_entity)
         + (SELECT count(*) FROM actor_strategic_connection_check)
         + (SELECT count(*) FROM person_verification_event)
      INTO held;
    IF held <> 0 THEN
        RAISE EXCEPTION
            'refusing to roll back: % row(s) of sourced evidence exist in the new tables',
            held;
    END IF;
END $$;

-- Guards.
DROP TRIGGER IF EXISTS event_ghus_notes_guard ON event;
DROP TRIGGER IF EXISTS actor_ghus_notes_guard ON actor;
DROP FUNCTION IF EXISTS ghus_guard_notes_column();

DROP TRIGGER IF EXISTS actor_ranking_university_only ON actor_ranking;
DROP FUNCTION IF EXISTS ghus_guard_ranking_is_university();

DROP TRIGGER IF EXISTS person_verification_event_append_only ON person_verification_event;

DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY[
        'actor', 'person', 'event', 'hub', 'hub_actor', 'actor_topic', 'actor_location'
    ] LOOP
        IF to_regclass('public.' || target) IS NOT NULL THEN
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', target || '_no_delete', target);
        END IF;
    END LOOP;
END $$;

DROP FUNCTION IF EXISTS ghus_guard_no_delete();

-- Tables.
DROP TABLE IF EXISTS person_verification_event;
DROP TABLE IF EXISTS actor_strategic_connection_check;
DROP TABLE IF EXISTS strategic_entity;

-- hub_actor history.
ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS ck_hub_actor_superseded;
ALTER TABLE hub_actor
    DROP COLUMN IF EXISTS assigned_by,
    DROP COLUMN IF EXISTS superseded_by,
    DROP COLUMN IF EXISTS superseded_at,
    DROP COLUMN IF EXISTS is_current;

-- collection_run provenance.
ALTER TABLE collection_run DROP CONSTRAINT IF EXISTS ck_collection_run_counts;
ALTER TABLE collection_run DROP CONSTRAINT IF EXISTS ck_collection_run_cadence;
ALTER TABLE collection_run DROP CONSTRAINT IF EXISTS ck_collection_run_trigger_type;
ALTER TABLE collection_run
    DROP COLUMN IF EXISTS review_item_count,
    DROP COLUMN IF EXISTS staged_count,
    DROP COLUMN IF EXISTS deduplicated_count,
    DROP COLUMN IF EXISTS found_count,
    DROP COLUMN IF EXISTS config_snapshot,
    DROP COLUMN IF EXISTS initiated_by,
    DROP COLUMN IF EXISTS cadence,
    DROP COLUMN IF EXISTS trigger_type;

COMMIT;
