-- Migration 810: remove the tables Compass does not use (platform owner's decisions, 24 and 25 Nov 2026).
-- Written for the database after 800 (actor names). It replaces the earlier draft numbered 750,
-- which was never applied (750 went to Nouhaila's organization details fields).
--
-- Never used, or replaced:
--   actor_ranking                   university rankings; planned, never filled (and its guard function)
--   actor_evaluation                old Phase 1 evaluations; nothing reads them
--   event_scoring                   old Phase 1 event scores; nothing reads them
--   fetched_document                an earlier design for fetched pages; raw_document replaced it
--   canonical_write_audit           a planned write log; never filled
--   contact_collection_authorization  contact collection was never built
--   query_log                       telemetry of the July Ask prototype; nothing writes to it
--   proposal                        an inbox from the first database (June); Review does this job
--   hub_center_review               hub-centre drift reviews; the code that wrote it was never called
--   person_topic                    a person's topics; nothing ever wrote it
-- History only (archived first: GHUS-data/backups/archive-810-removed-tables-20261125.sql):
--   legacy_migration_record, actor_category_migration_audit, hub_actor_removed, hub_removed
--                                   records of the 6 Oct move to Architecture V2 (and the
--                                   function ghus_pre_cutover_data_loss_audit that read them)
--   review_queue                    duplicate pairs from August; review_item replaced it
--   alembic_version, schema_migrations  markers of the June database and the July prototype
--
-- Kept on purpose: compass.migration_snapshot (800's rollback needs it), challenge,
-- actor_relevance, partnership_profile, event_sector, actor_merge_log, the two cutover records,
-- strategic_document, strategic_entity and actor_strategic_connection_check.
-- (proposal is left out of the function check below: the word appears in unrelated code.)
--
-- One transaction. It refuses, changing nothing, unless 800 is applied and 810 is not, every
-- table is there, the tables that were never filled are still empty, and nothing else (a
-- foreign key, a view, a trigger or another function) depends on them.
-- Rollback: rollback/810_remove_unused_tables.sql (structure); the rows are in the archive.

BEGIN;

DO $$
DECLARE
    removed regclass[];
    found text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '800') THEN
        RAISE EXCEPTION '810 needs 800 (actor names) applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '810') THEN
        RAISE EXCEPTION '810 is already applied';
    END IF;
    removed := ARRAY[to_regclass('public.actor_ranking'), to_regclass('public.actor_evaluation'),
                     to_regclass('public.event_scoring'), to_regclass('public.fetched_document'),
                     to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'),
                     to_regclass('public.query_log'), to_regclass('public.proposal'),
                     to_regclass('public.hub_center_review'), to_regclass('public.person_topic'),
                     to_regclass('public.legacy_migration_record'), to_regclass('public.actor_category_migration_audit'),
                     to_regclass('public.hub_actor_removed'), to_regclass('public.hub_removed'),
                     to_regclass('public.review_queue'), to_regclass('public.alembic_version'),
                     to_regclass('public.schema_migrations')];
    IF array_position(removed, NULL) IS NOT NULL THEN
        RAISE EXCEPTION 'a table 810 removes is missing; nothing to do';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE oid = ANY (removed) AND relkind <> 'r') THEN
        RAISE EXCEPTION 'one of them is not a plain table (a stand-in view?)';
    END IF;
    IF EXISTS (SELECT 1 FROM public.actor_ranking) OR EXISTS (SELECT 1 FROM public.fetched_document)
       OR EXISTS (SELECT 1 FROM public.canonical_write_audit) OR EXISTS (SELECT 1 FROM public.contact_collection_authorization)
       OR EXISTS (SELECT 1 FROM public.proposal) OR EXISTS (SELECT 1 FROM public.hub_center_review)
       OR EXISTS (SELECT 1 FROM public.person_topic) THEN
        RAISE EXCEPTION 'a table that was never filled now has rows; it is in use';
    END IF;
    SELECT string_agg(DISTINCT conrelid::regclass::text, ', ') INTO found
      FROM pg_constraint WHERE contype = 'f' AND confrelid = ANY (removed) AND NOT conrelid = ANY (removed);
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'other tables point to them: %', found;
    END IF;
    SELECT string_agg(DISTINCT v.oid::regclass::text, ', ') INTO found
      FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class
     WHERE d.refobjid = ANY (removed) AND NOT v.oid = ANY (removed);
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'views read them: %', found;
    END IF;
    SELECT string_agg(tgrelid::regclass::text || '.' || tgname, ', ') INTO found
      FROM pg_trigger
     WHERE tgfoid = 'public.ghus_guard_ranking_is_university()'::regprocedure
       AND tgrelid <> 'public.actor_ranking'::regclass;
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'ghus_guard_ranking_is_university is used elsewhere: %', found;
    END IF;
    SELECT string_agg(DISTINCT p.oid::regprocedure::text, ', ') INTO found
      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname IN ('public', 'compass')
       AND p.oid NOT IN ('public.ghus_guard_ranking_is_university()'::regprocedure,
                         'public.ghus_pre_cutover_data_loss_audit()'::regprocedure)
       AND p.prosrc ~ ('\m(' || array_to_string(ARRAY['actor_ranking', 'actor_evaluation', 'event_scoring',
                       'fetched_document', 'canonical_write_audit', 'contact_collection_authorization', 'query_log',
                       'hub_center_review', 'person_topic', 'legacy_migration_record', 'actor_category_migration_audit',
                       'hub_actor_removed', 'hub_removed', 'review_queue', 'alembic_version', 'schema_migrations',
                       'ghus_pre_cutover_data_loss_audit'], '|') || ')\M');
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'other database functions mention them: %', found;
    END IF;
END $$;

DROP TABLE public.actor_ranking;
DROP FUNCTION public.ghus_guard_ranking_is_university();
DROP TABLE public.actor_evaluation;
DROP TABLE public.event_scoring;
DROP TABLE public.fetched_document;
DROP TABLE public.canonical_write_audit;
DROP TABLE public.contact_collection_authorization;
DROP TABLE public.query_log;
DROP TABLE public.proposal;
DROP TABLE public.hub_center_review;
DROP TABLE public.person_topic;
DROP FUNCTION public.ghus_pre_cutover_data_loss_audit();
DROP TABLE public.legacy_migration_record;
DROP TABLE public.actor_category_migration_audit;
DROP TABLE public.hub_actor_removed;
DROP TABLE public.hub_removed;
DROP TABLE public.review_queue;
DROP TABLE public.alembic_version;
DROP TABLE public.schema_migrations;

NOTIFY pgrst, 'reload schema';

COMMIT;
