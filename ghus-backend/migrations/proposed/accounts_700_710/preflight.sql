-- Read-only preflight for migrations 700 (Compass accounts) and 710 (record deletion,
-- 30-day retention). Run in the Supabase SQL editor BEFORE applying them; every row
-- must say ok = true. Changes nothing.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'Supabase Auth users table exists' AS check_name,
           to_regclass('auth.users') IS NOT NULL AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'auth.users.id is uuid',
           EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'auth' AND table_name = 'users'
                      AND column_name = 'id' AND data_type = 'uuid'), NULL
    UNION ALL
    SELECT 3, 'schema compass does not exist yet', to_regnamespace('compass') IS NULL, NULL
    UNION ALL
    SELECT 4, 'ledger has no 700 or 710 row',
           NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                        WHERE migration_id IN ('700', '710')), NULL
    UNION ALL
    SELECT 5, 'gen_random_uuid() available', to_regproc('gen_random_uuid') IS NOT NULL, NULL
    UNION ALL
    SELECT 6, 'the four delete guards are as reviewed (710 replaces them)',
           g.found = 'ghus_guard_no_delete=50d5a4d149ae6ddab671711995f74503 '
                     'ghus_guard_sector_link_append_only=9085b6f48d8b09b4b0c1e2dca80f7ee8 '
                     'ghus_guard_subscription_run_append_only=437b46f7461d47c29f76a81c36784b89 '
                     'ghus_reject_mutation=6738d523481ae9fa0efd0792f3c45fa8', g.found
      FROM (SELECT string_agg(proname || '=' || md5(prosrc), ' ' ORDER BY proname) AS found
              FROM pg_proc WHERE pronamespace = 'public'::regnamespace
               AND proname IN ('ghus_guard_no_delete', 'ghus_reject_mutation',
                               'ghus_guard_sector_link_append_only',
                               'ghus_guard_subscription_run_append_only')) g
    UNION ALL
    SELECT 7, 'actor_read columns are as reviewed (710 adds one filter)',
           v.found = '22020ae7a529542d7c1e04d3ff6783fb', v.found
      FROM (SELECT md5(string_agg(column_name || ':' || data_type, ',' ORDER BY ordinal_position)) AS found
              FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'actor_read') v
    UNION ALL
    -- The cleanup's per-table policy covers these; a link it does not know blocks
    -- the purge (never deletes it). Compare with docs/schema-review/02_PERMANENT_DELETION.md.
    SELECT 8, 'foreign keys into organizations, people, events, hubs (informational)', true,
           (SELECT string_agg(DISTINCT src.relname || '→' || ref.relname, ', ')
              FROM pg_constraint c JOIN pg_class src ON src.oid = c.conrelid
              JOIN pg_class ref ON ref.oid = c.confrelid
             WHERE c.contype = 'f' AND ref.relnamespace = 'public'::regnamespace
               AND ref.relname IN ('actor', 'person', 'event', 'hub'))
    UNION ALL
    SELECT 9, 'latest ledger entries (informational)', true,
           (SELECT string_agg(migration_id, ', ' ORDER BY applied_at DESC)
              FROM (SELECT migration_id, applied_at FROM public.architecture_v2_migration_ledger
                     ORDER BY applied_at DESC LIMIT 5) l)
) checks ORDER BY n;

ROLLBACK;
