-- Read-only preflight for migration 820 (topic becomes sector; nine more tables go). Run in the
-- Supabase SQL editor BEFORE applying it; every row must say ok = true. Changes nothing.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'migration 810 applied, 820 not' AS check_name,
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '810')
           AND NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '820') AS ok,
           NULL::text AS detail
    UNION ALL
    SELECT 2, 'the 10 tables exist, as tables', array_position(ARRAY[to_regclass('public.topic'), to_regclass('public.actor_topic'), to_regclass('public.event_topic'), to_regclass('public.actor_location'), to_regclass('public.actor_relevance'), to_regclass('public.challenge'), to_regclass('public.person_discovery_profile'), to_regclass('public.event_claim'), to_regclass('public.architecture_v2_cutover_attestation'), to_regclass('public.architecture_v2_cutover_baseline')], NULL) IS NULL
           AND NOT EXISTS (SELECT 1 FROM pg_class WHERE oid = ANY (ARRAY[to_regclass('public.topic'), to_regclass('public.actor_topic'), to_regclass('public.event_topic'), to_regclass('public.actor_location'), to_regclass('public.actor_relevance'), to_regclass('public.challenge'), to_regclass('public.person_discovery_profile'), to_regclass('public.event_claim'), to_regclass('public.architecture_v2_cutover_attestation'), to_regclass('public.architecture_v2_cutover_baseline')]) AND relkind <> 'r'), NULL
    UNION ALL
    SELECT 3, 'every topic has one sector with the same code',
           NOT EXISTS (SELECT 1 FROM public.topic t WHERE (SELECT count(*) FROM public.sector s WHERE s.code = t.code) <> 1),
           (SELECT string_agg(code, ', ' ORDER BY code) FROM public.topic)
    UNION ALL
    SELECT 4, 'the links into topic are the 12 reviewed ones',
           (SELECT string_agg(conrelid::regclass::text, ',' ORDER BY conrelid::regclass::text) FROM pg_constraint
             WHERE contype = 'f' AND confrelid = 'public.topic'::regclass)
           = 'actor_fact,actor_fact_current_pointer,actor_strategic_connection_check,actor_topic,actor_verification_event,collection_request,entity_edge,event_topic,hub_assignment_evidence,proposed_hub,record_verification,review_item', NULL
    UNION ALL
    SELECT 5, 'the links into sector are the 4 reviewed ones',
           (SELECT string_agg(conrelid::regclass::text, ',' ORDER BY conrelid::regclass::text) FROM pg_constraint
             WHERE contype = 'f' AND confrelid = 'public.sector'::regclass) = 'actor_sector,event_sector,hub_sector,sector', NULL
    UNION ALL
    SELECT 6, 'actor_location holds nothing the organization rows do not',
           NOT EXISTS (SELECT 1 FROM public.actor_location l LEFT JOIN public.actor a ON a.actor_id = l.actor_id
                        WHERE a.actor_id IS NULL OR a.city IS DISTINCT FROM l.city OR a.state_code IS DISTINCT FROM l.state_code
                           OR a.latitude IS DISTINCT FROM l.latitude OR a.longitude IS DISTINCT FROM l.longitude),
           (SELECT count(*)::text FROM public.actor_location) || ' rows'
    UNION ALL
    SELECT 7, 'no view other than actor_template reads them',
           NOT EXISTS (SELECT 1 FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class
                        WHERE d.refobjid = ANY (ARRAY[to_regclass('public.topic'), to_regclass('public.actor_topic'), to_regclass('public.event_topic'), to_regclass('public.actor_location'), to_regclass('public.actor_relevance'), to_regclass('public.challenge'), to_regclass('public.person_discovery_profile'), to_regclass('public.event_claim'), to_regclass('public.architecture_v2_cutover_attestation'), to_regclass('public.architecture_v2_cutover_baseline')]) AND NOT v.oid = ANY (ARRAY[to_regclass('public.topic'), to_regclass('public.actor_topic'), to_regclass('public.event_topic'), to_regclass('public.actor_location'), to_regclass('public.actor_relevance'), to_regclass('public.challenge'), to_regclass('public.person_discovery_profile'), to_regclass('public.event_claim'), to_regclass('public.architecture_v2_cutover_attestation'), to_regclass('public.architecture_v2_cutover_baseline')]) AND v.relname <> 'actor_template'), NULL
    UNION ALL
    SELECT 8, 'person has no research_area / public_profile_url yet',
           NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'person'
                        AND column_name IN ('research_area', 'public_profile_url')), NULL
    UNION ALL
    SELECT 9, 'rows that go (informational; archived and in the backup)', true,
           'topic ' || (SELECT count(*) FROM public.topic) || ', actor_topic ' || (SELECT count(*) FROM public.actor_topic)
           || ', event_topic ' || (SELECT count(*) FROM public.event_topic) || ', actor_location ' || (SELECT count(*) FROM public.actor_location)
           || ', actor_relevance ' || (SELECT count(*) FROM public.actor_relevance) || ', challenge ' || (SELECT count(*) FROM public.challenge)
           || ', person_discovery_profile ' || (SELECT count(*) FROM public.person_discovery_profile)
           || ', event_claim ' || (SELECT count(*) FROM public.event_claim)
           || ', cutover records ' || (SELECT count(*) FROM public.architecture_v2_cutover_attestation)
           || ' + ' || (SELECT count(*) FROM public.architecture_v2_cutover_baseline)
) checks ORDER BY n;

ROLLBACK;
