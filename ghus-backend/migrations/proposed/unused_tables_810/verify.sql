-- Read-only checks after migration 810; every row must say ok = true.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'the 17 tables are gone' AS check_name,
           NOT EXISTS (SELECT 1 FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace
                        AND c.relname = ANY ('{actor_ranking,actor_evaluation,event_scoring,fetched_document,canonical_write_audit,contact_collection_authorization,query_log,proposal,hub_center_review,person_topic,legacy_migration_record,actor_category_migration_audit,hub_actor_removed,hub_removed,review_queue,alembic_version,schema_migrations}'::text[])) AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'ghus_guard_ranking_is_university and ghus_pre_cutover_data_loss_audit are gone',
           NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname IN ('ghus_guard_ranking_is_university', 'ghus_pre_cutover_data_loss_audit')), NULL
    UNION ALL
    SELECT 3, 'kept: migration_snapshot, challenge, actor_relevance, partnership_profile, event_sector, actor_merge_log, strategic tables, cutover records',
           to_regclass('compass.migration_snapshot') IS NOT NULL AND to_regclass('public.challenge') IS NOT NULL
           AND to_regclass('public.actor_relevance') IS NOT NULL AND to_regclass('public.partnership_profile') IS NOT NULL
           AND to_regclass('public.event_sector') IS NOT NULL AND to_regclass('public.actor_merge_log') IS NOT NULL
           AND to_regclass('public.strategic_document') IS NOT NULL AND to_regclass('public.strategic_entity') IS NOT NULL
           AND to_regclass('public.actor_strategic_connection_check') IS NOT NULL
           AND to_regclass('public.architecture_v2_cutover_attestation') IS NOT NULL
           AND to_regclass('public.architecture_v2_cutover_baseline') IS NOT NULL, NULL
    UNION ALL
    SELECT 4, 'the Directory still reads (actor_read)',
           (SELECT count(*) FROM public.actor_read) > 0, (SELECT count(*)::text FROM public.actor_read)
    UNION ALL
    SELECT 5, 'the accounts tables are intact (compass has 11 tables)',
           (SELECT count(*) FROM pg_class WHERE relnamespace = 'compass'::regnamespace AND relkind = 'r') = 11,
           (SELECT count(*)::text FROM pg_class WHERE relnamespace = 'compass'::regnamespace AND relkind = 'r')
    UNION ALL
    SELECT 6, 'the ledger has the 810 row with this checksum',
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '810' AND source_sha256 = '372d76107f0a2cdf99165725e3df3920118b819e5577273d9c419e4ee575d4d9'), NULL
) checks ORDER BY n;

ROLLBACK;
