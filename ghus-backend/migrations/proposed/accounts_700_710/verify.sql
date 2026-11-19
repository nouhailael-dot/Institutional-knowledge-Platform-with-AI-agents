-- Read-only verification after 700, 710 and the ledger rows. Every row must say ok = true.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'compass tables present' AS check_name,
           (SELECT count(*) FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
             WHERE s.nspname = 'compass' AND c.relkind = 'r'
               AND c.relname IN ('permission', 'role', 'role_permission', 'user_profile', 'invitation',
                                 'audit_event', 'record_owner', 'usage_event', 'notification',
                                 'deleted_record', 'migration_snapshot')) = 11 AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'row security on every compass table',
           NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
                        WHERE s.nspname = 'compass' AND c.relkind = 'r' AND NOT c.relrowsecurity), NULL
    UNION ALL
    SELECT 3, 'browser roles cannot use schema compass',
           NOT has_schema_privilege('anon', 'compass', 'USAGE')
           AND NOT has_schema_privilege('authenticated', 'compass', 'USAGE'), NULL
    UNION ALL
    SELECT 4, 'roles seeded: admin, editor, viewer',
           (SELECT string_agg(code, ',' ORDER BY code) FROM compass.role) = 'admin,editor,viewer', NULL
    UNION ALL
    SELECT 5, 'no user, invitation or deletion yet',
           (SELECT count(*) FROM compass.user_profile) + (SELECT count(*) FROM compass.invitation)
           + (SELECT count(*) FROM compass.deleted_record) = 0, NULL
    UNION ALL
    SELECT 6, 'delete guards carry the purge door',
           (SELECT count(*) FROM pg_proc WHERE pronamespace = 'public'::regnamespace
               AND proname IN ('ghus_guard_no_delete', 'ghus_reject_mutation',
                               'ghus_guard_sector_link_append_only', 'ghus_guard_subscription_run_append_only')
               AND prosrc LIKE '%compass.purge_door_open()%') = 4, NULL
    UNION ALL
    SELECT 7, 'purge door is closed', compass.purge_door_open() IS FALSE, NULL
    UNION ALL
    SELECT 8, 'actor_read hides pending deletions',
           pg_get_viewdef('public.actor_read'::regclass) LIKE '%compass.deleted_record%', NULL
    UNION ALL
    SELECT 9, 'rollback definitions saved', (SELECT count(*) FROM compass.migration_snapshot
                                              WHERE migration_id = '710') = 5, NULL
    UNION ALL
    SELECT 10, 'ledger rows 700 and 710',
           (SELECT count(*) FROM public.architecture_v2_migration_ledger
             WHERE migration_id IN ('700', '710')) = 2, NULL
    UNION ALL
    SELECT 11, 'organizations visible as before (count)', true,
           (SELECT count(*)::text FROM public.actor_read)
) checks ORDER BY n;

ROLLBACK;
