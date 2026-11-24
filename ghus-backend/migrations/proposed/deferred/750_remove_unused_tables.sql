-- Migration 750: remove the tables Compass no longer uses (platform owner's decision, 24 Nov 2026).
--
--   organization_ranking           university rankings; planned, never filled. With it go its
--                                  720 stand-in view actor_ranking and its guard function.
--   organization_evaluation        old Phase 1 evaluations; nothing reads them. With it goes its
--                                  720 stand-in view actor_evaluation.
--   event_scoring                  old Phase 1 event scores; nothing reads them.
--   fetched_document               an earlier design for fetched pages; raw_document replaced it.
--   canonical_write_audit          a planned write log; nothing ever filled it.
--   contact_collection_authorization  contact collection was never built.
--   query_log                      telemetry of the July Ask prototype; nothing writes to it.
--   compass.migration_snapshot     definitions saved for rolling back 710 and 720; its rows are
--                                  kept in unused_tables_750/restore_migration_snapshot.sql, so
--                                  those rollbacks stay possible.
--
-- Kept on purpose: challenge, strategic_document, strategic_entity and
-- organization_strategic_connection_check (planned work: NutriCrops, personalization, the
-- UM6P/OCP check).
--
-- One transaction. It refuses, changing nothing, unless 720 is applied, 750 is not, the
-- tables that were never filled are still empty, and nothing else depends on these tables.
-- The rows of organization_evaluation (158), event_scoring (87) and query_log (7) go with
-- them; the backup taken before applying keeps them. The code needs no change: every
-- reader skips a table that does not exist.
-- Rollback: rollback/750_remove_unused_tables.sql, then unused_tables_750/restore_migration_snapshot.sql.

BEGIN;

DO $$
DECLARE
    removed regclass[];
    found text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '720') THEN
        RAISE EXCEPTION '750 needs 720 (organization names) applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '750') THEN
        RAISE EXCEPTION '750 is already applied';
    END IF;
    removed := ARRAY[to_regclass('public.organization_ranking'), to_regclass('public.organization_evaluation'),
                     to_regclass('public.event_scoring'), to_regclass('public.fetched_document'),
                     to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'),
                     to_regclass('public.query_log'), to_regclass('compass.migration_snapshot')];
    IF array_position(removed, NULL) IS NOT NULL THEN
        RAISE EXCEPTION 'a table 750 removes is missing; nothing to do';
    END IF;
    IF (SELECT relkind::text FROM pg_class WHERE oid = to_regclass('public.actor_ranking')) IS DISTINCT FROM 'v'
       OR (SELECT relkind::text FROM pg_class WHERE oid = to_regclass('public.actor_evaluation')) IS DISTINCT FROM 'v' THEN
        RAISE EXCEPTION 'actor_ranking or actor_evaluation is not the 720 stand-in view';
    END IF;
    IF EXISTS (SELECT 1 FROM public.organization_ranking) OR EXISTS (SELECT 1 FROM public.fetched_document)
       OR EXISTS (SELECT 1 FROM public.canonical_write_audit) OR EXISTS (SELECT 1 FROM public.contact_collection_authorization) THEN
        RAISE EXCEPTION 'a table that was never filled now has rows; it is in use';
    END IF;
    SELECT string_agg(DISTINCT conrelid::regclass::text, ', ') INTO found
      FROM pg_constraint WHERE contype = 'f' AND confrelid = ANY (removed) AND NOT conrelid = ANY (removed);
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'other tables point to them: %', found;
    END IF;
    SELECT string_agg(DISTINCT v.oid::regclass::text, ', ') INTO found
      FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class
     WHERE d.refobjid = ANY (removed) AND NOT v.oid = ANY (removed)
       AND v.oid NOT IN (to_regclass('public.actor_ranking'), to_regclass('public.actor_evaluation'));
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'views read them: %', found;
    END IF;
    SELECT string_agg(tgrelid::regclass::text || '.' || tgname, ', ') INTO found
      FROM pg_trigger
     WHERE tgfoid = 'public.ghus_guard_ranking_is_university()'::regprocedure
       AND tgrelid <> 'public.organization_ranking'::regclass;
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'ghus_guard_ranking_is_university is used elsewhere: %', found;
    END IF;
END $$;

DROP VIEW public.actor_ranking;
DROP VIEW public.actor_evaluation;
DROP TABLE public.organization_ranking;
DROP FUNCTION public.ghus_guard_ranking_is_university();
DROP TABLE public.organization_evaluation;
DROP TABLE public.event_scoring;
DROP TABLE public.fetched_document;
DROP TABLE public.canonical_write_audit;
DROP TABLE public.contact_collection_authorization;
DROP TABLE public.query_log;
DROP TABLE compass.migration_snapshot;

COMMIT;
