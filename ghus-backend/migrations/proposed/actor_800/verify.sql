-- Read-only checks after migration 800; every row must say ok = true.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'no relation named organization is left' AS check_name,
           NOT EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'public'::regnamespace
                        AND relname LIKE '%organization%' AND relkind IN ('r','v','m','p')) AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'the 20 actor tables are real tables again',
           count(*) = 20, count(*)::text
      FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r','p')
       AND relname = ANY ('{hub_actor,hub_actor_removed,actor,actor_category_definition,actor_category_migration_audit,actor_category_type_definition,actor_evaluation,actor_fact,actor_fact_current_pointer,actor_location,actor_merge_log,actor_person,actor_ranking,actor_relevance,actor_sector,actor_strategic_connection_check,actor_topic,actor_update_subscription,actor_update_subscription_run,actor_verification_event}'::text[])
    UNION ALL
    SELECT 3, 'the 7 views carry the actor names',
           count(*) = 7, count(*)::text
      FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('v','m')
       AND relname = ANY ('{actor_descendant_edge,actor_descendants,actor_fact_current,actor_fact_current_v2,actor_fact_history,actor_read,actor_template}'::text[])
    UNION ALL
    SELECT 4, 'no column named organization on them',
           NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                        AND column_name LIKE '%organization%'
                        AND table_name = ANY ('{hub_actor,hub_actor_removed,actor,actor_category_definition,actor_category_migration_audit,actor_category_type_definition,actor_evaluation,actor_fact,actor_fact_current_pointer,actor_location,actor_merge_log,actor_person,actor_ranking,actor_relevance,actor_sector,actor_strategic_connection_check,actor_topic,actor_update_subscription,actor_update_subscription_run,actor_verification_event,actor_descendant_edge,actor_descendants,actor_fact_current,actor_fact_current_v2,actor_fact_history,actor_read,actor_template}'::text[])), NULL
    UNION ALL
    SELECT 5, 'no function named organization is left',
           NOT EXISTS (SELECT 1 FROM pg_proc WHERE pronamespace = 'public'::regnamespace
                        AND proname LIKE '%organization%'), NULL
    UNION ALL
    SELECT 6, 'every trigger on the actor tables points at an existing function',
           NOT EXISTS (SELECT 1 FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid
                        WHERE NOT tg.tgisinternal AND c.relname = ANY ('{hub_actor,hub_actor_removed,actor,actor_category_definition,actor_category_migration_audit,actor_category_type_definition,actor_evaluation,actor_fact,actor_fact_current_pointer,actor_location,actor_merge_log,actor_person,actor_ranking,actor_relevance,actor_sector,actor_strategic_connection_check,actor_topic,actor_update_subscription,actor_update_subscription_run,actor_verification_event}'::text[])
                          AND NOT EXISTS (SELECT 1 FROM pg_proc p WHERE p.oid = tg.tgfoid)), NULL
    UNION ALL
    SELECT 7, 'the details triggers are back on the fact tables',
           count(*) = 2, count(*)::text
      FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('actor_details_follows_pointer',
                                                            'actor_details_follows_topicless_fact')
    UNION ALL
    SELECT 8, 'actor rows (the platform''s count)', true, (SELECT count(*)::text FROM public.actor)
    UNION ALL
    SELECT 9, 'actor_template rows', true, (SELECT count(*)::text FROM public.actor_template)
    UNION ALL
    SELECT 10, 'ledger row 800 with the reviewed checksum',
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '800' AND source_sha256 = '829d46a5f25c5cf0168ede3dab5fda876f10caed5c3e17e8848239cceeab0e55'), NULL
) checks ORDER BY n;

ROLLBACK;
