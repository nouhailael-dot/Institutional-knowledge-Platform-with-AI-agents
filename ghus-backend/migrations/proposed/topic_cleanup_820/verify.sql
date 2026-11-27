-- Read-only checks after migration 820; every row must say ok = true.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'the 10 tables are gone' AS check_name,
           NOT EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'public'::regnamespace
                        AND relname = ANY ('{topic,actor_topic,event_topic,actor_location,actor_relevance,challenge,person_discovery_profile,event_claim,architecture_v2_cutover_attestation,architecture_v2_cutover_baseline}'::text[])) AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'every stored topic_id names a sector',
           NOT EXISTS (SELECT 1 FROM public.actor_fact f WHERE f.topic_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.sector s WHERE s.sector_id = f.topic_id))
           AND NOT EXISTS (SELECT 1 FROM public.hub h WHERE NOT EXISTS (SELECT 1 FROM public.sector s WHERE s.sector_id = h.topic_id))
           AND NOT EXISTS (SELECT 1 FROM public.hub_actor ha WHERE NOT EXISTS (SELECT 1 FROM public.sector s WHERE s.sector_id = ha.topic_id))
           AND NOT EXISTS (SELECT 1 FROM public.collection_request r WHERE r.topic_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.sector s WHERE s.sector_id = r.topic_id))
           AND NOT EXISTS (SELECT 1 FROM public.review_item i WHERE i.topic_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.sector s WHERE s.sector_id = i.topic_id)),
           (SELECT count(*)::text FROM public.actor_fact WHERE topic_id IS NOT NULL) || ' facts with a sector'
    UNION ALL
    SELECT 3, 'the sector links all point to a sector, none lost',
           NOT EXISTS (SELECT 1 FROM public.actor_sector x WHERE NOT EXISTS (SELECT 1 FROM public.sector s WHERE s.sector_id = x.sector_id)),
           (SELECT count(*)::text FROM public.actor_sector) || ' organization links, '
           || (SELECT count(*)::text FROM public.event_sector) || ' event links, '
           || (SELECT count(*)::text FROM public.hub_sector) || ' hub links'
    UNION ALL
    SELECT 4, 'the 8 thematic sectors and 10 sectors in all', (SELECT count(*) FROM public.sector WHERE is_thematic) = 8
           AND (SELECT count(*) FROM public.sector) = 10, (SELECT string_agg(code, ', ' ORDER BY code) FROM public.sector WHERE is_thematic)
    UNION ALL
    SELECT 5, 'the actor_sector guard is on again',
           (SELECT tgenabled FROM pg_trigger WHERE tgrelid = 'public.actor_sector'::regclass AND tgname = 'actor_sector_append_only') = 'O', NULL
    UNION ALL
    SELECT 6, 'person has research_area and public_profile_url',
           (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'person'
             AND column_name IN ('research_area', 'public_profile_url')) = 2, NULL
    UNION ALL
    SELECT 7, 'actor_template reads, without a topic column',
           (SELECT count(*) FROM public.actor_template) > 0
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'actor_template' AND column_name = 'topic'),
           (SELECT count(*)::text FROM public.actor_template)
    UNION ALL
    SELECT 8, 'the Directory still reads (actor_read)',
           (SELECT count(*) FROM public.actor_read) > 0, (SELECT count(*)::text FROM public.actor_read)
    UNION ALL
    SELECT 9, 'the ledger has the 820 row with this checksum',
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '820' AND source_sha256 = 'ee52cf07bda96dd38b8a2af237a9861f1246099ce36b2879a85b476899e44e6a'), NULL
) checks ORDER BY n;

ROLLBACK;
