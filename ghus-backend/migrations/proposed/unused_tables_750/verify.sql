-- Read-only checks after migration 750; every row must say ok = true.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'organization_ranking is gone' AS check_name,
           to_regclass('public.organization_ranking') IS NULL AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'its stand-in view actor_ranking is gone', to_regclass('public.actor_ranking') IS NULL, NULL
    UNION ALL
    SELECT 3, 'query_log is gone', to_regclass('public.query_log') IS NULL, NULL
    UNION ALL
    SELECT 4, 'ghus_guard_ranking_is_university is gone',
           NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'ghus_guard_ranking_is_university'
                        AND pronamespace = 'public'::regnamespace), NULL
    UNION ALL
    SELECT 5, 'challenge, strategic_document and organization_relevance are still there',
           to_regclass('public.challenge') IS NOT NULL AND to_regclass('public.strategic_document') IS NOT NULL
           AND to_regclass('public.organization_relevance') IS NOT NULL, NULL
    UNION ALL
    SELECT 6, 'the Directory still reads (organization_read)',
           (SELECT count(*) FROM public.organization_read) > 0,
           (SELECT count(*)::text FROM public.organization_read)
    UNION ALL
    SELECT 7, 'the ledger has the 750 row with this checksum',
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '750' AND source_sha256 = 'c41b46263ecf7925f7e8473d0fc6d53f0c027846c3389ea88eaecb170c5f532f'), NULL
) checks ORDER BY n;

ROLLBACK;
