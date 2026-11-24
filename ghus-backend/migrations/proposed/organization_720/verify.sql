-- Read-only checks after migration 720; every row must say ok = true.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'the 27 renamed relations exist' AS check_name,
           count(*) = 27 AS ok, count(*)::text AS detail
      FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r','v')
       AND relname = ANY ('{organization,organization_category_definition,organization_category_migration_audit,organization_category_type_definition,organization_details,organization_evaluation,organization_fact,organization_fact_current_pointer,organization_location,organization_merge_log,organization_person,organization_ranking,organization_relevance,organization_sector,organization_strategic_connection_check,organization_topic,organization_update_subscription,organization_update_subscription_run,organization_verification_event,hub_organization,hub_organization_removed,organization_descendant_edge,organization_descendants,organization_fact_current,organization_fact_current_v2,organization_fact_history,organization_read}'::text[])
    UNION ALL
    SELECT 2, 'every old name is now a stand-in view',
           count(*) = 27, count(*)::text
      FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'v'
       AND relname = ANY ('{actor,actor_category_definition,actor_category_migration_audit,actor_category_type_definition,actor_details,actor_evaluation,actor_fact,actor_fact_current_pointer,actor_location,actor_merge_log,actor_person,actor_ranking,actor_relevance,actor_sector,actor_strategic_connection_check,actor_topic,actor_update_subscription,actor_update_subscription_run,actor_verification_event,hub_actor,hub_actor_removed,actor_descendant_edge,actor_descendants,actor_fact_current,actor_fact_current_v2,actor_fact_history,actor_read}'::text[])
    UNION ALL
    SELECT 3, 'the stand-ins run with the caller''s rights',
           bool_and(coalesce(c.reloptions::text, '') LIKE '%security_invoker=true%'), NULL
      FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'v'
       AND c.relname = ANY ('{actor,actor_category_definition,actor_category_migration_audit,actor_category_type_definition,actor_details,actor_evaluation,actor_fact,actor_fact_current_pointer,actor_location,actor_merge_log,actor_person,actor_ranking,actor_relevance,actor_sector,actor_strategic_connection_check,actor_topic,actor_update_subscription,actor_update_subscription_run,actor_verification_event,hub_actor,hub_actor_removed,actor_descendant_edge,actor_descendants,actor_fact_current,actor_fact_current_v2,actor_fact_history,actor_read}'::text[])
    UNION ALL
    SELECT 4, 'anon and authenticated have no access to the stand-ins',
           NOT EXISTS (SELECT 1 FROM information_schema.role_table_grants
                        WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')
                          AND table_name = ANY ('{actor,actor_category_definition,actor_category_migration_audit,actor_category_type_definition,actor_details,actor_evaluation,actor_fact,actor_fact_current_pointer,actor_location,actor_merge_log,actor_person,actor_ranking,actor_relevance,actor_sector,actor_strategic_connection_check,actor_topic,actor_update_subscription,actor_update_subscription_run,actor_verification_event,hub_actor,hub_actor_removed,actor_descendant_edge,actor_descendants,actor_fact_current,actor_fact_current_v2,actor_fact_history,actor_read}'::text[])), NULL
    UNION ALL
    SELECT 5, 'organization.organization_id exists',
           EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                    AND table_name = 'organization' AND column_name = 'organization_id'), NULL
    UNION ALL
    SELECT 6, 'no column named actor left on a renamed relation',
           NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                        AND column_name LIKE '%actor%'
                        AND table_name = ANY ('{organization,organization_category_definition,organization_category_migration_audit,organization_category_type_definition,organization_details,organization_evaluation,organization_fact,organization_fact_current_pointer,organization_location,organization_merge_log,organization_person,organization_ranking,organization_relevance,organization_sector,organization_strategic_connection_check,organization_topic,organization_update_subscription,organization_update_subscription_run,organization_verification_event,hub_organization,hub_organization_removed,organization_descendant_edge,organization_descendants,organization_fact_current,organization_fact_current_v2,organization_fact_history,organization_read}'::text[])), NULL
    UNION ALL
    SELECT 7, 'the rewritten functions exist',
           count(*) = 9, count(*)::text
      FROM pg_proc WHERE pronamespace = 'public'::regnamespace
       AND proname = ANY ('{ghus_organization_details_on_pointer,ghus_organization_details_on_topicless_fact,ghus_guard_organization_status,ghus_prevent_organization_family_cycle,ghus_project_organization_verification_status,ghus_guard_ranking_is_university,ghus_guard_subscription_run_append_only,ghus_validate_entity_edge,ghus_organization_details_refresh}'::text[])
    UNION ALL
    SELECT 8, 'the label reads Company / Corporate Organization',
           EXISTS (SELECT 1 FROM public.organization_category_definition
                    WHERE display_name LIKE '%Corporate Organization%')
           AND NOT EXISTS (SELECT 1 FROM public.organization_category_definition
                            WHERE display_name LIKE '%Corporate Actor%'), NULL
    UNION ALL
    SELECT 9, 'the old names still read the same rows',
           (SELECT count(*) FROM public.actor) = (SELECT count(*) FROM public.organization), NULL
    UNION ALL
    SELECT 10, 'ledger row 720 with the reviewed checksum',
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '720' AND source_sha256 = '7f4a032812feda93ed4a57bbfac165d6bd3b734082d4a53bcba5ae51c60dd359'), NULL
) checks ORDER BY n;

ROLLBACK;
