-- Read-only checks after migration 750; every row must say ok = true.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'the 8 tables and the 2 stand-in views are gone' AS check_name,
           NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname IN ('public', 'compass') AND c.relname = ANY ('{organization_ranking,organization_evaluation,event_scoring,fetched_document,canonical_write_audit,contact_collection_authorization,query_log,migration_snapshot,actor_ranking,actor_evaluation}'::text[])) AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'ghus_guard_ranking_is_university is gone',
           NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'ghus_guard_ranking_is_university'), NULL
    UNION ALL
    SELECT 3, 'kept: challenge, strategic_document, strategic_entity, organization_strategic_connection_check, organization_relevance',
           to_regclass('public.challenge') IS NOT NULL AND to_regclass('public.strategic_document') IS NOT NULL
           AND to_regclass('public.strategic_entity') IS NOT NULL
           AND to_regclass('public.organization_strategic_connection_check') IS NOT NULL
           AND to_regclass('public.organization_relevance') IS NOT NULL, NULL
    UNION ALL
    SELECT 4, 'the Directory still reads (organization_read)',
           (SELECT count(*) FROM public.organization_read) > 0, (SELECT count(*)::text FROM public.organization_read)
    UNION ALL
    SELECT 5, 'the accounts tables are intact (compass has 10 tables)',
           (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'compass' AND c.relkind = 'r') = 10,
           (SELECT count(*)::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'compass' AND c.relkind = 'r')
    UNION ALL
    SELECT 6, 'the ledger has the 750 row with this checksum',
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '750' AND source_sha256 = '6af4e59fdbc92c90afa22d5a4b42719caadb773803c27c74057b69e7f042f32f'), NULL
) checks ORDER BY n;

ROLLBACK;
