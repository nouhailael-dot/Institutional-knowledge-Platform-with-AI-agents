-- Migration 730: remove two tables Compass never uses (platform owner's decision, 24 Nov 2026).
--
--   organization_ranking  (actor_ranking before 720): university rankings, never filled.
--                          With it go its stand-in view actor_ranking (720) and its
--                          guard function ghus_guard_ranking_is_university.
--   query_log             : telemetry of the July Ask prototype; nothing writes to it.
--
-- Kept on purpose: challenge (holds the NutriCrops challenge; organization_relevance
-- points to it) and strategic_document (for attached strategy documents).
--
-- One transaction. It refuses, changing nothing, unless 720 is applied, 730 is not,
-- organization_ranking is empty, and nothing else depends on the two tables.
-- The code needs no change: every reader skips a table that does not exist.
-- Rollback: rollback/730_remove_unused_tables.sql (recreates the objects; query_log's
-- rows come back only from the backup taken before applying).

BEGIN;

DO $$
DECLARE
    dependents text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '720') THEN
        RAISE EXCEPTION '730 needs 720 (organization names) applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '730') THEN
        RAISE EXCEPTION '730 is already applied';
    END IF;
    IF to_regclass('public.organization_ranking') IS NULL OR to_regclass('public.query_log') IS NULL THEN
        RAISE EXCEPTION 'organization_ranking or query_log is missing; nothing to remove';
    END IF;
    IF (SELECT relkind::text FROM pg_class WHERE oid = 'public.actor_ranking'::regclass) <> 'v' THEN
        RAISE EXCEPTION 'actor_ranking is not the 720 stand-in view';
    END IF;
    IF EXISTS (SELECT 1 FROM public.organization_ranking) THEN
        RAISE EXCEPTION 'organization_ranking has rows; it is not unused';
    END IF;
    SELECT string_agg(DISTINCT conrelid::regclass::text, ', ') INTO dependents
      FROM pg_constraint
     WHERE contype = 'f' AND confrelid IN ('public.organization_ranking'::regclass, 'public.query_log'::regclass)
       AND conrelid NOT IN ('public.organization_ranking'::regclass, 'public.query_log'::regclass);
    IF dependents IS NOT NULL THEN
        RAISE EXCEPTION 'other tables point to them: %', dependents;
    END IF;
    SELECT string_agg(DISTINCT v.relname, ', ') INTO dependents
      FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class
     WHERE d.refobjid IN ('public.organization_ranking'::regclass, 'public.query_log'::regclass)
       AND v.relname <> 'actor_ranking';
    IF dependents IS NOT NULL THEN
        RAISE EXCEPTION 'views read them: %', dependents;
    END IF;
    SELECT string_agg(tgrelid::regclass::text || '.' || tgname, ', ') INTO dependents
      FROM pg_trigger
     WHERE tgfoid = 'public.ghus_guard_ranking_is_university()'::regprocedure
       AND tgrelid <> 'public.organization_ranking'::regclass;
    IF dependents IS NOT NULL THEN
        RAISE EXCEPTION 'ghus_guard_ranking_is_university is used elsewhere: %', dependents;
    END IF;
END $$;

DROP VIEW public.actor_ranking;
DROP TABLE public.organization_ranking;
DROP FUNCTION public.ghus_guard_ranking_is_university();
DROP TABLE public.query_log;

COMMIT;
