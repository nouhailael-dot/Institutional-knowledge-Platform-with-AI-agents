-- Migration 820: topic becomes sector, and nine more tables go (platform owner's decision, 27 Nov 2026).
--
-- topic was a second copy of the eight thematic sectors (same codes, same names). Instead of
-- rewriting every stored topic_id (facts, history, hubs, Review items, requests: append-only
-- records), each of those eight sectors takes the id its topic had. The sector links
-- (actor_sector, event_sector, hub_sector) follow the new ids; every topic_id column then
-- points to sector. The column keeps its name, topic_id, until the actor -> organization
-- rename; it now holds a sector id.
--
-- Removed:
--   topic, actor_topic, event_topic    the topic list and its links (actor_sector and
--                                      event_sector hold the same links)
--   actor_location                     one row per organization, identical to the
--                                      organization's own city, state and coordinates
--   actor_relevance, challenge         the June NutriCrops assessment (rows archived)
--   person_discovery_profile           merged into person: research_area, public_profile_url
--   event_claim                        standing claims are kept as event facts from now on
--   architecture_v2_cutover_attestation, architecture_v2_cutover_baseline
--                                      records of the 6 Oct move (rows archived)
-- actor_template (Nouhaila's 730 view) is recreated without its Topic column, like the
-- Organizations template.
--
-- One transaction. It refuses, changing nothing, unless 810 is applied and 820 is not, every
-- topic has a sector with the same code, the links into topic and sector are the reviewed
-- ones, nothing else depends on the removed tables, and actor_location holds nothing the
-- organization rows do not. The actor_sector append-only guard is switched off for the one
-- statement that moves its sector ids, and on again in the same transaction.
-- Rows are archived before applying: GHUS-data/backups/archive-820-*.sql.
-- Rollback: rollback/820_topic_into_sector_and_cleanup.sql.

BEGIN;

DO $$
DECLARE
    removed regclass[];
    found text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '810') THEN
        RAISE EXCEPTION '820 needs 810 applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '820') THEN
        RAISE EXCEPTION '820 is already applied';
    END IF;
    removed := ARRAY[to_regclass('public.topic'), to_regclass('public.actor_topic'), to_regclass('public.event_topic'),
                     to_regclass('public.actor_location'), to_regclass('public.actor_relevance'),
                     to_regclass('public.challenge'), to_regclass('public.person_discovery_profile'),
                     to_regclass('public.event_claim'), to_regclass('public.architecture_v2_cutover_attestation'),
                     to_regclass('public.architecture_v2_cutover_baseline')];
    IF array_position(removed, NULL) IS NOT NULL THEN
        RAISE EXCEPTION 'a table 820 removes is missing; nothing to do';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE oid = ANY (removed) AND relkind <> 'r') THEN
        RAISE EXCEPTION 'one of them is not a plain table';
    END IF;
    -- every topic has exactly one sector with its code, and no sector already has a topic id
    IF EXISTS (SELECT 1 FROM public.topic t WHERE (SELECT count(*) FROM public.sector s WHERE s.code = t.code) <> 1) THEN
        RAISE EXCEPTION 'a topic has no sector with the same code';
    END IF;
    IF EXISTS (SELECT 1 FROM public.sector s JOIN public.topic t ON t.topic_id = s.sector_id) THEN
        RAISE EXCEPTION 'a sector already carries a topic id';
    END IF;
    IF to_regclass('public.person') IS NULL OR EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'person' AND column_name IN ('research_area', 'public_profile_url')) THEN
        RAISE EXCEPTION 'person already has research_area or public_profile_url';
    END IF;
    -- the links into topic and sector are exactly the reviewed ones
    SELECT string_agg(conrelid::regclass::text, ',' ORDER BY conrelid::regclass::text) INTO found
      FROM pg_constraint WHERE contype = 'f' AND confrelid = 'public.topic'::regclass;
    IF found IS DISTINCT FROM 'actor_fact,actor_fact_current_pointer,actor_strategic_connection_check,actor_topic,actor_verification_event,collection_request,entity_edge,event_topic,hub_assignment_evidence,proposed_hub,record_verification,review_item' THEN
        RAISE EXCEPTION 'the links into topic differ from the reviewed ones: %', found;
    END IF;
    SELECT string_agg(conrelid::regclass::text, ',' ORDER BY conrelid::regclass::text) INTO found
      FROM pg_constraint WHERE contype = 'f' AND confrelid = 'public.sector'::regclass;
    IF found IS DISTINCT FROM 'actor_sector,event_sector,hub_sector,sector' THEN
        RAISE EXCEPTION 'the links into sector differ from the reviewed ones: %', found;
    END IF;
    -- nothing else points to the other removed tables
    SELECT string_agg(DISTINCT conrelid::regclass::text, ', ') INTO found
      FROM pg_constraint WHERE contype = 'f' AND confrelid = ANY (removed[2:]) AND NOT conrelid = ANY (removed);
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'other tables point to them: %', found;
    END IF;
    SELECT string_agg(DISTINCT v.oid::regclass::text, ', ') INTO found
      FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class
     WHERE d.refobjid = ANY (removed) AND NOT v.oid = ANY (removed) AND v.oid <> 'public.actor_template'::regclass;
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'views read them: %', found;
    END IF;
    SELECT string_agg(DISTINCT p.oid::regprocedure::text, ', ') INTO found
      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname IN ('public', 'compass')
       AND p.prosrc ~ '\m(topic|actor_topic|event_topic|actor_location|actor_relevance|challenge|person_discovery_profile|event_claim|architecture_v2_cutover_attestation|architecture_v2_cutover_baseline)\M';
    IF found IS NOT NULL THEN
        RAISE EXCEPTION 'database functions mention them: %', found;
    END IF;
    -- actor_location holds nothing the organization rows do not
    IF EXISTS (SELECT 1 FROM public.actor_location l LEFT JOIN public.actor a ON a.actor_id = l.actor_id
                WHERE a.actor_id IS NULL OR a.city IS DISTINCT FROM l.city OR a.state_code IS DISTINCT FROM l.state_code
                   OR a.latitude IS DISTINCT FROM l.latitude OR a.longitude IS DISTINCT FROM l.longitude) THEN
        RAISE EXCEPTION 'actor_location holds a location the organization row does not; review it first';
    END IF;
END $$;

-- 1. Nouhaila's template view reads topic; it is recreated at the end.
DROP VIEW public.actor_template;

-- 2. Every link into topic and sector comes off while the ids move.
ALTER TABLE public.actor_fact DROP CONSTRAINT actor_fact_topic_id_fkey;
ALTER TABLE public.actor_fact_current_pointer DROP CONSTRAINT actor_fact_current_pointer_topic_id_fkey;
ALTER TABLE public.actor_strategic_connection_check DROP CONSTRAINT actor_strategic_connection_check_topic_id_fkey;
ALTER TABLE public.actor_verification_event DROP CONSTRAINT actor_verification_event_topic_id_fkey;
ALTER TABLE public.collection_request DROP CONSTRAINT collection_request_topic_id_fkey;
ALTER TABLE public.entity_edge DROP CONSTRAINT entity_edge_topic_id_fkey;
ALTER TABLE public.hub_assignment_evidence DROP CONSTRAINT hub_assignment_evidence_topic_id_fkey;
ALTER TABLE public.proposed_hub DROP CONSTRAINT fk_proposed_hub_topic;
ALTER TABLE public.record_verification DROP CONSTRAINT record_verification_topic_id_fkey;
ALTER TABLE public.review_item DROP CONSTRAINT review_item_topic_id_fkey;
ALTER TABLE public.actor_sector DROP CONSTRAINT actor_sector_sector_id_fkey;
ALTER TABLE public.event_sector DROP CONSTRAINT event_sector_sector_id_fkey;
ALTER TABLE public.hub_sector DROP CONSTRAINT hub_sector_sector_id_fkey;
ALTER TABLE public.sector DROP CONSTRAINT sector_parent_sector_id_fkey;

-- 3. Each thematic sector takes its topic's id; its links follow.
CREATE TEMP TABLE sector_id_move ON COMMIT DROP AS
    SELECT s.sector_id AS old_id, t.topic_id AS new_id FROM public.sector s JOIN public.topic t ON t.code = s.code;
UPDATE public.sector s SET sector_id = m.new_id FROM sector_id_move m WHERE s.sector_id = m.old_id;
UPDATE public.sector s SET parent_sector_id = m.new_id FROM sector_id_move m WHERE s.parent_sector_id = m.old_id;
ALTER TABLE public.actor_sector DISABLE TRIGGER actor_sector_append_only;
UPDATE public.actor_sector x SET sector_id = m.new_id FROM sector_id_move m WHERE x.sector_id = m.old_id;
ALTER TABLE public.actor_sector ENABLE TRIGGER actor_sector_append_only;
UPDATE public.event_sector x SET sector_id = m.new_id FROM sector_id_move m WHERE x.sector_id = m.old_id;
UPDATE public.hub_sector x SET sector_id = m.new_id FROM sector_id_move m WHERE x.sector_id = m.old_id;

-- 4. The links go back on, every topic_id now pointing to sector.
ALTER TABLE public.actor_sector ADD CONSTRAINT actor_sector_sector_id_fkey FOREIGN KEY (sector_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.event_sector ADD CONSTRAINT event_sector_sector_id_fkey FOREIGN KEY (sector_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.hub_sector ADD CONSTRAINT hub_sector_sector_id_fkey FOREIGN KEY (sector_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.sector ADD CONSTRAINT sector_parent_sector_id_fkey FOREIGN KEY (parent_sector_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.actor_fact ADD CONSTRAINT actor_fact_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.actor_fact_current_pointer ADD CONSTRAINT actor_fact_current_pointer_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.actor_strategic_connection_check ADD CONSTRAINT actor_strategic_connection_check_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.actor_verification_event ADD CONSTRAINT actor_verification_event_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.collection_request ADD CONSTRAINT collection_request_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.entity_edge ADD CONSTRAINT entity_edge_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.hub_assignment_evidence ADD CONSTRAINT hub_assignment_evidence_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.proposed_hub ADD CONSTRAINT fk_proposed_hub_topic FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id) NOT VALID;
ALTER TABLE public.record_verification ADD CONSTRAINT record_verification_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.review_item ADD CONSTRAINT review_item_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.hub ADD CONSTRAINT hub_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.sector(sector_id);
COMMENT ON COLUMN public.actor_fact.topic_id IS 'The thematic sector this fact was collected for (a topic until migration 820).';
COMMENT ON COLUMN public.hub.topic_id IS 'The thematic sector of the hub (a topic until migration 820).';
COMMENT ON COLUMN public.collection_request.topic_id IS 'The thematic sector the request is for (a topic until migration 820).';

-- 5. The person keeps its research area and public profile page itself.
ALTER TABLE public.person ADD COLUMN research_area text, ADD COLUMN public_profile_url text;
UPDATE public.person p SET research_area = COALESCE(p.research_area, d.research_area),
                           public_profile_url = COALESCE(p.public_profile_url, d.public_profile_url)
  FROM (SELECT DISTINCT ON (person_id) person_id, research_area, public_profile_url
          FROM public.person_discovery_profile ORDER BY person_id, fetched_at DESC NULLS LAST, created_at DESC) d
 WHERE d.person_id = p.person_id;

-- 6. The tables go.
DROP TABLE public.actor_topic;
DROP TABLE public.event_topic;
DROP TABLE public.topic;
DROP TABLE public.actor_location;
DROP TABLE public.actor_relevance;
DROP TABLE public.challenge;
DROP TABLE public.person_discovery_profile;
DROP TABLE public.event_claim;
DROP TABLE public.architecture_v2_cutover_attestation;
DROP TABLE public.architecture_v2_cutover_baseline;

-- 7. The template view again, without its Topic column (the templates have none since 820).
CREATE VIEW public.actor_template WITH (security_invoker = true) AS
 SELECT o.actor_id,
    o.name,
    array_to_string(o.alt_names, '; '::text) AS alternate_names,
    o.website,
    cat.display_name AS actor_category,
    COALESCE(ctype.display_name, o.category_type) AS category_type,
    o.category_note,
    o.description,
    sec.primary_sector,
    sec.additional_sectors,
    o.city,
    o.state_code,
    reg.display_name AS region,
    o.country,
    par.parent_name,
    par.parent_relationship,
    src.url AS source_url,
    o.recent_activity,
    NULL::text AS recent_activity_date,
    o.funding_signal,
    o.international_connection,
    o.primary_technical_focus,
    o.technical_approach,
    o.current_activities,
    o.funding_summary,
    o.ghus_notes,
    o.um6p_ocp_connection,
    o.topic_unit_and_work,
    o.institution_control,
    o.land_grant_designation,
    o.relevant_centers_programs,
    o.parent_and_center_type,
    o.topic_research_focus,
    o.active_recent_projects,
    o.main_funders,
    o.sponsoring_agency,
    o.formal_national_designation,
    o.topic_program_area,
    o.facility_type_operator,
    o.testing_demonstration_scope,
    o.current_project,
    o.clinical_research_focus,
    o.parent_academic_link,
    o.hospital_type_scale,
    o.current_initiative,
    o.ownership_and_size,
    o.topic_business_segment_product,
    o.mapped_geography_operations,
    NULL::text AS development_stage,
    o.technology_and_problem,
    o.founding_year_location,
    o.funding_stage,
    o.pilot_customer_evidence,
    o.platform_type_operator,
    o.sector_focus,
    o.platform_offerings,
    o.scale_indicator,
    o.investor_type_headquarters,
    o.sector_stage_focus,
    o.geographic_focus,
    o.published_fund_size,
    o.topic_investment_thesis,
    o.jurisdiction_parent_agency,
    o.topic_mandate_program,
    o.visible_funding_programs,
    o.mission_sector_focus,
    o.relevant_program,
    o.programs_grant_themes,
    o.association_type,
    o.sector_geographic_scope,
    o.member_types,
    o.current_initiative_working_group,
    o.linked_members,
    o.network_scope_locations,
    o.status
   FROM public.actor o
     LEFT JOIN public.actor_category_definition cat ON cat.category_code = o.actor_category
     LEFT JOIN public.actor_category_type_definition ctype ON ctype.category_code = o.actor_category AND ctype.type_code = o.category_type
     LEFT JOIN public.region_definition reg ON reg.region_code = o.region_code
     LEFT JOIN public.source src ON src.source_id = o.source_id
     LEFT JOIN LATERAL ( SELECT max(s.name::text) FILTER (WHERE os.is_primary) AS primary_sector,
            string_agg(s.name::text, '; '::text ORDER BY (s.name::text)) FILTER (WHERE NOT os.is_primary OR os.is_primary IS NULL) AS additional_sectors
           FROM public.actor_sector os
             JOIN public.sector s ON s.sector_id = os.sector_id
          WHERE os.actor_id = o.actor_id) sec ON true
     LEFT JOIN LATERAL ( SELECT p.name AS parent_name,
            replace(e.relationship_type, '_'::text, ' '::text) AS parent_relationship
           FROM public.entity_edge e
             JOIN public.actor p ON p.actor_id = e.object_id
          WHERE e.subject_id = o.actor_id AND (e.subject_type = ANY (ARRAY['actor'::text, 'organization'::text])) AND (e.object_type = ANY (ARRAY['actor'::text, 'organization'::text])) AND (e.relationship_type = ANY (ARRAY['unit_of'::text, 'operated_by'::text]))
          ORDER BY e.created_at DESC
         LIMIT 1) par ON true
  WHERE o.merged_into_actor_id IS NULL;
COMMENT ON VIEW public.actor_template IS 'Organizations template (2026-11-12.1) as a view: one row per organization, template column order. Migration 730; Topic column removed by 820.';
COMMENT ON COLUMN public.actor_template.name IS 'Official name';
COMMENT ON COLUMN public.actor_template.alternate_names IS 'Other names';
COMMENT ON COLUMN public.actor_template.website IS 'Website';
COMMENT ON COLUMN public.actor_template.actor_category IS 'Organization Category';
COMMENT ON COLUMN public.actor_template.category_type IS 'Category Type';
COMMENT ON COLUMN public.actor_template.category_note IS 'Category note';
COMMENT ON COLUMN public.actor_template.description IS 'Description';
COMMENT ON COLUMN public.actor_template.primary_sector IS 'Sector';
COMMENT ON COLUMN public.actor_template.additional_sectors IS 'Additional sectors';
COMMENT ON COLUMN public.actor_template.city IS 'City';
COMMENT ON COLUMN public.actor_template.state_code IS 'State';
COMMENT ON COLUMN public.actor_template.region IS 'Region';
COMMENT ON COLUMN public.actor_template.country IS 'Country';
COMMENT ON COLUMN public.actor_template.parent_name IS 'Parent organization';
COMMENT ON COLUMN public.actor_template.parent_relationship IS 'Relationship to parent';
COMMENT ON COLUMN public.actor_template.source_url IS 'Source URL';
COMMENT ON COLUMN public.actor_template.recent_activity_date IS 'Recent activity date (no column of its own: empty)';
COMMENT ON COLUMN public.actor_template.ghus_notes IS 'GHUS Notes';
COMMENT ON COLUMN public.actor_template.um6p_ocp_connection IS 'UM6P/OCP connection';
COMMENT ON COLUMN public.actor_template.development_stage IS 'Startup: development stage (no column of its own: empty)';

NOTIFY pgrst, 'reload schema';

COMMIT;
