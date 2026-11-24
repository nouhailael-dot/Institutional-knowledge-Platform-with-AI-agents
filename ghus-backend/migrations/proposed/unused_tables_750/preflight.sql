-- Read-only preflight for migration 750 (remove two unused tables). Run in the Supabase
-- SQL editor BEFORE applying it; every row must say ok = true. Changes nothing.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'migration 720 applied' AS check_name,
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '720') AS ok,
           NULL::text AS detail
    UNION ALL
    SELECT 2, 'ledger has no 750 row',
           NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '750'), NULL
    UNION ALL
    SELECT 3, 'organization_ranking exists and is empty',
           to_regclass('public.organization_ranking') IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM public.organization_ranking),
           (SELECT count(*)::text FROM public.organization_ranking)
    UNION ALL
    SELECT 4, 'actor_ranking is the 720 stand-in view',
           (SELECT relkind::text FROM pg_class WHERE oid = to_regclass('public.actor_ranking')) = 'v', NULL
    UNION ALL
    SELECT 5, 'query_log exists (its rows are informational: they go, the backup keeps them)',
           to_regclass('public.query_log') IS NOT NULL,
           (SELECT count(*)::text || ' rows' FROM public.query_log)
    UNION ALL
    SELECT 6, 'no other table points to them',
           NOT EXISTS (SELECT 1 FROM pg_constraint
                        WHERE contype = 'f'
                          AND confrelid IN (to_regclass('public.organization_ranking'), to_regclass('public.query_log'))
                          AND conrelid NOT IN (to_regclass('public.organization_ranking'), to_regclass('public.query_log'))),
           NULL
    UNION ALL
    SELECT 7, 'no view reads them except actor_ranking',
           NOT EXISTS (SELECT 1 FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class
                        WHERE d.refobjid IN (to_regclass('public.organization_ranking'), to_regclass('public.query_log'))
                          AND v.relname <> 'actor_ranking'),
           NULL
    UNION ALL
    SELECT 8, 'ghus_guard_ranking_is_university is used only by organization_ranking',
           NOT EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
                        WHERE p.proname = 'ghus_guard_ranking_is_university'
                          AND t.tgrelid <> to_regclass('public.organization_ranking')),
           NULL
    UNION ALL
    SELECT 9, 'kept: challenge and strategic_document are untouched (informational)', true,
           (SELECT count(*)::text FROM public.challenge) || ' challenge row(s)'
) checks ORDER BY n;

ROLLBACK;
