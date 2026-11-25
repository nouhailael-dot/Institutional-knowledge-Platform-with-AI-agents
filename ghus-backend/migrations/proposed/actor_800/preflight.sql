-- Read-only preflight for migration 800 (organization -> actor names). Run BEFORE applying;
-- every row must say ok = true. Changes nothing.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'compass.migration_snapshot exists' AS check_name,
           to_regclass('compass.migration_snapshot') IS NOT NULL AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'ledger has no 800 row',
           NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '800'), NULL
    UNION ALL
    SELECT 3, 'the latest migration is still 790',
           l.m = '790', l.m
      FROM (SELECT migration_id AS m FROM public.architecture_v2_migration_ledger ORDER BY applied_at DESC LIMIT 1) l
    UNION ALL
    SELECT 4, 'the relations named organization are the reviewed 27', f.found = 'hub_organization:r, hub_organization_removed:r, organization:r, organization_category_definition:r, organization_category_migration_audit:r, organization_category_type_definition:r, organization_evaluation:r, organization_fact:r, organization_fact_current_pointer:r, organization_location:r, organization_merge_log:r, organization_person:r, organization_ranking:r, organization_relevance:r, organization_sector:r, organization_strategic_connection_check:r, organization_topic:r, organization_update_subscription:r, organization_update_subscription_run:r, organization_verification_event:r, organization_descendant_edge:v, organization_descendants:v, organization_fact_current:v, organization_fact_current_v2:v, organization_fact_history:v, organization_read:v, organization_template:v', f.found
      FROM (SELECT string_agg(relname || ':' || relkind::text, ', ' ORDER BY relkind, relname) AS found
              FROM pg_class WHERE relnamespace = 'public'::regnamespace
               AND relname LIKE '%organization%' AND relkind IN ('r','v','m','p')) f
    UNION ALL
    SELECT 5, 'the actor stand-ins are the reviewed 26', s.found = 'actor,actor_category_definition,actor_category_migration_audit,actor_category_type_definition,actor_descendant_edge,actor_descendants,actor_evaluation,actor_fact,actor_fact_current,actor_fact_current_pointer,actor_fact_current_v2,actor_fact_history,actor_location,actor_merge_log,actor_person,actor_ranking,actor_read,actor_relevance,actor_sector,actor_strategic_connection_check,actor_topic,actor_update_subscription,actor_update_subscription_run,actor_verification_event,hub_actor,hub_actor_removed', s.found
      FROM (SELECT string_agg(relname, ',' ORDER BY relname) AS found FROM pg_class
             WHERE relnamespace = 'public'::regnamespace AND relkind = 'v'
               AND relname = ANY ('{hub_actor,hub_actor_removed,actor,actor_category_definition,actor_category_migration_audit,actor_category_type_definition,actor_evaluation,actor_fact,actor_fact_current_pointer,actor_location,actor_merge_log,actor_person,actor_ranking,actor_relevance,actor_sector,actor_strategic_connection_check,actor_topic,actor_update_subscription,actor_update_subscription_run,actor_verification_event,actor_descendant_edge,actor_descendants,actor_fact_current,actor_fact_current_v2,actor_fact_history,actor_read,actor_template}'::text[])) s
    UNION ALL
    SELECT 6, 'the functions 800 rewrites are as reviewed', g.found = 'ghus_guard_organization_status=79ee4a866301ac87769c082b71834614 ghus_guard_ranking_is_university=6fdd630187f7bffbb46b5bc8574072a7 ghus_guard_subscription_run_append_only=575a4cdc05eb3a2995807307762a5329 ghus_organization_details_on_pointer=505ffe75c4ede1521ddf7d0309a91839 ghus_organization_details_on_topicless_fact=505ffe75c4ede1521ddf7d0309a91839 ghus_organization_details_refresh=42ed8b4a7b5e6350fb380ca6a2bd412d ghus_prevent_organization_family_cycle=d26dc6562cd14ebdc4ee8bf921cf95ee ghus_project_organization_verification_status=6937f673c34fd81e45219e89e7bc75c7 ghus_validate_entity_edge=d1594c2919f6088793ab4c643a3874f2', g.found
      FROM (SELECT string_agg(proname || '=' || md5(replace(prosrc, chr(13) || chr(10), chr(10))), ' ' ORDER BY proname) AS found
              FROM pg_proc WHERE pronamespace = 'public'::regnamespace
               AND proname = ANY ('{ghus_guard_organization_status,ghus_guard_ranking_is_university,ghus_guard_subscription_run_append_only,ghus_organization_details_on_pointer,ghus_organization_details_on_topicless_fact,ghus_organization_details_refresh,ghus_prevent_organization_family_cycle,ghus_project_organization_verification_status,ghus_validate_entity_edge}'::text[])) g
) checks ORDER BY n;

ROLLBACK;
