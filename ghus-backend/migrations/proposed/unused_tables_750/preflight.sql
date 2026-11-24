-- Read-only preflight for migration 750 (remove the unused tables). Run in the Supabase SQL
-- editor BEFORE applying it; every row must say ok = true. Changes nothing.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'migration 720 applied' AS check_name,
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '720') AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'ledger has no 750 row',
           NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '750'), NULL
    UNION ALL
    SELECT 3, 'the 8 tables to remove all exist', array_position(ARRAY[to_regclass('public.organization_ranking'), to_regclass('public.organization_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('compass.migration_snapshot')], NULL) IS NULL, NULL
    UNION ALL
    SELECT 4, 'the never-filled tables are still empty',
           NOT EXISTS (SELECT 1 FROM public.organization_ranking) AND NOT EXISTS (SELECT 1 FROM public.fetched_document)
           AND NOT EXISTS (SELECT 1 FROM public.canonical_write_audit)
           AND NOT EXISTS (SELECT 1 FROM public.contact_collection_authorization), NULL
    UNION ALL
    SELECT 5, 'rows that go with them (informational; the backup keeps them)', true,
           'organization_evaluation ' || (SELECT count(*) FROM public.organization_evaluation)
           || ', event_scoring ' || (SELECT count(*) FROM public.event_scoring)
           || ', query_log ' || (SELECT count(*) FROM public.query_log)
           || ', migration_snapshot ' || (SELECT count(*) FROM compass.migration_snapshot) || ' (saved in restore_migration_snapshot.sql)'
    UNION ALL
    SELECT 6, 'actor_ranking and actor_evaluation are the 720 stand-in views',
           (SELECT relkind::text FROM pg_class WHERE oid = to_regclass('public.actor_ranking')) = 'v'
           AND (SELECT relkind::text FROM pg_class WHERE oid = to_regclass('public.actor_evaluation')) = 'v', NULL
    UNION ALL
    SELECT 7, 'no other table points to them',
           NOT EXISTS (SELECT 1 FROM pg_constraint WHERE contype = 'f'
                        AND confrelid = ANY (ARRAY[to_regclass('public.organization_ranking'), to_regclass('public.organization_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('compass.migration_snapshot')]) AND NOT conrelid = ANY (ARRAY[to_regclass('public.organization_ranking'), to_regclass('public.organization_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('compass.migration_snapshot')])), NULL
    UNION ALL
    SELECT 8, 'no other view reads them',
           NOT EXISTS (SELECT 1 FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class
                        WHERE d.refobjid = ANY (ARRAY[to_regclass('public.organization_ranking'), to_regclass('public.organization_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('compass.migration_snapshot')]) AND NOT v.oid = ANY (ARRAY[to_regclass('public.organization_ranking'), to_regclass('public.organization_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('compass.migration_snapshot')])
                          AND v.relname NOT IN ('actor_ranking', 'actor_evaluation')), NULL
    UNION ALL
    SELECT 9, 'ghus_guard_ranking_is_university is used only by organization_ranking',
           NOT EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
                        WHERE p.proname = 'ghus_guard_ranking_is_university'
                          AND t.tgrelid <> to_regclass('public.organization_ranking')), NULL
) checks ORDER BY n;

ROLLBACK;
