-- Read-only preflight for migration 810 (remove the unused tables). Run in the Supabase SQL
-- editor BEFORE applying it; every row must say ok = true. Changes nothing.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'migration 800 (actor names) applied' AS check_name,
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '800') AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'ledger has no 810 row',
           NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '810'), NULL
    UNION ALL
    SELECT 3, 'the 17 tables to remove all exist, as tables',
           array_position(ARRAY[to_regclass('public.actor_ranking'), to_regclass('public.actor_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('public.proposal'), to_regclass('public.hub_center_review'), to_regclass('public.person_topic'), to_regclass('public.legacy_migration_record'), to_regclass('public.actor_category_migration_audit'), to_regclass('public.hub_actor_removed'), to_regclass('public.hub_removed'), to_regclass('public.review_queue'), to_regclass('public.alembic_version'), to_regclass('public.schema_migrations')], NULL) IS NULL
           AND NOT EXISTS (SELECT 1 FROM pg_class WHERE oid = ANY (ARRAY[to_regclass('public.actor_ranking'), to_regclass('public.actor_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('public.proposal'), to_regclass('public.hub_center_review'), to_regclass('public.person_topic'), to_regclass('public.legacy_migration_record'), to_regclass('public.actor_category_migration_audit'), to_regclass('public.hub_actor_removed'), to_regclass('public.hub_removed'), to_regclass('public.review_queue'), to_regclass('public.alembic_version'), to_regclass('public.schema_migrations')]) AND relkind <> 'r'), NULL
    UNION ALL
    SELECT 4, 'the never-filled tables are still empty',
           NOT EXISTS (SELECT 1 FROM public.actor_ranking)
           AND NOT EXISTS (SELECT 1 FROM public.fetched_document)
           AND NOT EXISTS (SELECT 1 FROM public.canonical_write_audit)
           AND NOT EXISTS (SELECT 1 FROM public.contact_collection_authorization)
           AND NOT EXISTS (SELECT 1 FROM public.proposal)
           AND NOT EXISTS (SELECT 1 FROM public.hub_center_review)
           AND NOT EXISTS (SELECT 1 FROM public.person_topic), NULL
    UNION ALL
    SELECT 5, 'no other table points to them',
           NOT EXISTS (SELECT 1 FROM pg_constraint WHERE contype = 'f'
                        AND confrelid = ANY (ARRAY[to_regclass('public.actor_ranking'), to_regclass('public.actor_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('public.proposal'), to_regclass('public.hub_center_review'), to_regclass('public.person_topic'), to_regclass('public.legacy_migration_record'), to_regclass('public.actor_category_migration_audit'), to_regclass('public.hub_actor_removed'), to_regclass('public.hub_removed'), to_regclass('public.review_queue'), to_regclass('public.alembic_version'), to_regclass('public.schema_migrations')]) AND NOT conrelid = ANY (ARRAY[to_regclass('public.actor_ranking'), to_regclass('public.actor_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('public.proposal'), to_regclass('public.hub_center_review'), to_regclass('public.person_topic'), to_regclass('public.legacy_migration_record'), to_regclass('public.actor_category_migration_audit'), to_regclass('public.hub_actor_removed'), to_regclass('public.hub_removed'), to_regclass('public.review_queue'), to_regclass('public.alembic_version'), to_regclass('public.schema_migrations')])), NULL
    UNION ALL
    SELECT 6, 'no view reads them',
           NOT EXISTS (SELECT 1 FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class
                        WHERE d.refobjid = ANY (ARRAY[to_regclass('public.actor_ranking'), to_regclass('public.actor_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('public.proposal'), to_regclass('public.hub_center_review'), to_regclass('public.person_topic'), to_regclass('public.legacy_migration_record'), to_regclass('public.actor_category_migration_audit'), to_regclass('public.hub_actor_removed'), to_regclass('public.hub_removed'), to_regclass('public.review_queue'), to_regclass('public.alembic_version'), to_regclass('public.schema_migrations')]) AND NOT v.oid = ANY (ARRAY[to_regclass('public.actor_ranking'), to_regclass('public.actor_evaluation'), to_regclass('public.event_scoring'), to_regclass('public.fetched_document'), to_regclass('public.canonical_write_audit'), to_regclass('public.contact_collection_authorization'), to_regclass('public.query_log'), to_regclass('public.proposal'), to_regclass('public.hub_center_review'), to_regclass('public.person_topic'), to_regclass('public.legacy_migration_record'), to_regclass('public.actor_category_migration_audit'), to_regclass('public.hub_actor_removed'), to_regclass('public.hub_removed'), to_regclass('public.review_queue'), to_regclass('public.alembic_version'), to_regclass('public.schema_migrations')])), NULL
    UNION ALL
    SELECT 7, 'ghus_guard_ranking_is_university is used only by actor_ranking',
           NOT EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
                        WHERE p.proname = 'ghus_guard_ranking_is_university'
                          AND t.tgrelid <> to_regclass('public.actor_ranking')), NULL
    UNION ALL
    SELECT 8, 'rows that go with them (informational; archived and in the backup)', true,
           'legacy_migration_record ' || (SELECT count(*) FROM public.legacy_migration_record)
           || ', actor_category_migration_audit ' || (SELECT count(*) FROM public.actor_category_migration_audit)
           || ', review_queue ' || (SELECT count(*) FROM public.review_queue)
           || ', hub_actor_removed ' || (SELECT count(*) FROM public.hub_actor_removed)
           || ', actor_evaluation ' || (SELECT count(*) FROM public.actor_evaluation)
           || ', event_scoring ' || (SELECT count(*) FROM public.event_scoring)
           || ', query_log ' || (SELECT count(*) FROM public.query_log)
           || ', schema_migrations ' || (SELECT count(*) FROM public.schema_migrations)
           || ', hub_removed ' || (SELECT count(*) FROM public.hub_removed)
           || ', alembic_version ' || (SELECT count(*) FROM public.alembic_version)
) checks ORDER BY n;

ROLLBACK;
