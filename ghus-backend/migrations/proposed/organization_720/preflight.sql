-- Read-only preflight for migration 720 (actor -> organization names). Run in the
-- Supabase SQL editor BEFORE applying it; every row must say ok = true. Changes nothing.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'migration 710 applied (compass.migration_snapshot exists)' AS check_name,
           to_regclass('compass.migration_snapshot') IS NOT NULL AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'ledger has no 720 row',
           NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '720'), NULL
    UNION ALL
    SELECT 3, 'no relation named organization yet',
           NOT EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'public'::regnamespace
                        AND relname LIKE '%organization%' AND relkind IN ('r','v','m')), NULL
    UNION ALL
    SELECT 4, 'the relations named actor are the reviewed 27', f.found = 'actor:r, actor_category_definition:r, actor_category_migration_audit:r, actor_category_type_definition:r, actor_details:r, actor_evaluation:r, actor_fact:r, actor_fact_current_pointer:r, actor_location:r, actor_merge_log:r, actor_person:r, actor_ranking:r, actor_relevance:r, actor_sector:r, actor_strategic_connection_check:r, actor_topic:r, actor_update_subscription:r, actor_update_subscription_run:r, actor_verification_event:r, hub_actor:r, hub_actor_removed:r, actor_descendant_edge:v, actor_descendants:v, actor_fact_current:v, actor_fact_current_v2:v, actor_fact_history:v, actor_read:v', f.found
      FROM (SELECT string_agg(relname || ':' || relkind::text, ', ' ORDER BY relkind, relname) AS found
              FROM pg_class WHERE relnamespace = 'public'::regnamespace
               AND relname LIKE '%actor%' AND relkind IN ('r','v','m')) f
    UNION ALL
    SELECT 5, 'the functions 720 rewrites are as reviewed', g.found = 'ghus_actor_details_on_pointer=37ae364a093c6d23fd4e43f536f01e35 ghus_actor_details_on_topicless_fact=37ae364a093c6d23fd4e43f536f01e35 ghus_actor_details_refresh=4d110357f4d926eaaf183a77d42704e7 ghus_guard_actor_status=d0db9ea0cf0ad4bfc2e68bc24f96a8b6 ghus_guard_ranking_is_university=c3e5f2ac92cb3e426ad2fdba8c21fbe9 ghus_guard_subscription_run_append_only=eeddb6cb99d0516f98c54dfc10822413 ghus_prevent_actor_family_cycle=c15c963372cfd4dfc1a2f7103bd98de5 ghus_project_actor_verification_status=3ec5ab6b24677b47762fff28ba4421ae ghus_validate_entity_edge=7992747063b1dc270cc91eede526fa1f', g.found
      FROM (SELECT string_agg(proname || '=' || md5(prosrc), ' ' ORDER BY proname) AS found
              FROM pg_proc WHERE pronamespace = 'public'::regnamespace
               AND proname IN ('ghus_actor_details_on_pointer', 'ghus_actor_details_on_topicless_fact', 'ghus_actor_details_refresh', 'ghus_guard_actor_status', 'ghus_guard_ranking_is_university', 'ghus_guard_subscription_run_append_only', 'ghus_prevent_actor_family_cycle', 'ghus_project_actor_verification_status', 'ghus_validate_entity_edge')) g
    UNION ALL
    SELECT 6, 'latest ledger entries (informational)', true,
           (SELECT string_agg(migration_id, ', ' ORDER BY applied_at DESC)
              FROM (SELECT migration_id, applied_at FROM public.architecture_v2_migration_ledger
                     ORDER BY applied_at DESC LIMIT 5) l)
) checks ORDER BY n;

ROLLBACK;
