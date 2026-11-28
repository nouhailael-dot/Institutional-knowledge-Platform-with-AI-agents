-- 790 (DRAFT, local copy only): organizations become one main table plus the diary,
-- like events and people in 760 (GHUS, 24 Nov 2026). To agree with the platform owner
-- before Supabase: it changes his 620/621 automatic copy and removes his 720 stand-in
-- actor_details.
--
--   * The 62 columns of organization_details (every fact the agents collect, one column
--     each) are added to public.organization, same names and types (jsonb), and their
--     current values are copied across (a data move: nothing is lost or changed).
--   * other_facts and fact_sources are not carried over: every reading, with its
--     source, stays in organization_fact.
--   * The automatic copy (ghus_organization_details_refresh, run when a current pointer
--     moves or a topicless reading is written) now writes into organization, and only
--     into those 62 columns: name, category, location, status and every other core
--     column are never written by it. A reading with no column stays in the facts only.
--   * organization_template reads organization directly; organization_details and its
--     stand-in actor_details are removed. No code reads either (24 Nov): Ismail's purge
--     skips a table that does not exist (decisions.py _exists).
--   * organization.updated_at is not touched by the move.
--   * Access: organization has row-level security and no public policy, like
--     organization_details had; anon and authenticated could read neither.
--
-- One transaction: any failure changes nothing. Rollback:
-- deferred/rollback/790_organization_one_table.sql (rebuilds organization_details from
-- these columns; other_facts and fact_sources come back empty).

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '770') THEN
        RAISE EXCEPTION '790 refused: migration 770 is not applied';
    END IF;
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '790') THEN
        RAISE EXCEPTION '790 refused: already in the ledger';
    END IF;
    IF (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public'
          AND table_name = 'organization_details') <> 66 THEN
        RAISE EXCEPTION '790 refused: organization_details is not the 66 columns 770 left';
    END IF;
END $guard$;

ALTER TABLE public.organization
    ADD COLUMN primary_technical_focus jsonb,
    ADD COLUMN technical_approach jsonb,
    ADD COLUMN current_activities jsonb,
    ADD COLUMN funding_summary jsonb,
    ADD COLUMN location jsonb,
    ADD COLUMN why_matched jsonb,
    ADD COLUMN recent_activity jsonb,
    ADD COLUMN funding_signal jsonb,
    ADD COLUMN international_connection jsonb,
    ADD COLUMN um6p_ocp_connection jsonb,
    ADD COLUMN current_initiative jsonb,
    ADD COLUMN current_initiative_working_group jsonb,
    ADD COLUMN current_project jsonb,
    ADD COLUMN pilot_customer_evidence jsonb,
    ADD COLUMN relevant_program jsonb,
    ADD COLUMN topic_unit_and_work jsonb,
    ADD COLUMN institution_control jsonb,
    ADD COLUMN land_grant_designation jsonb,
    ADD COLUMN rankings jsonb,
    ADD COLUMN relevant_centers_programs jsonb,
    ADD COLUMN parent_and_center_type jsonb,
    ADD COLUMN topic_research_focus jsonb,
    ADD COLUMN active_recent_projects jsonb,
    ADD COLUMN main_funders jsonb,
    ADD COLUMN sponsoring_agency jsonb,
    ADD COLUMN formal_national_designation jsonb,
    ADD COLUMN topic_program_area jsonb,
    ADD COLUMN facility_type_operator jsonb,
    ADD COLUMN testing_demonstration_scope jsonb,
    ADD COLUMN clinical_research_focus jsonb,
    ADD COLUMN parent_academic_link jsonb,
    ADD COLUMN hospital_type_scale jsonb,
    ADD COLUMN ownership_and_size jsonb,
    ADD COLUMN topic_business_segment_product jsonb,
    ADD COLUMN mapped_geography_operations jsonb,
    ADD COLUMN technology_and_problem jsonb,
    ADD COLUMN founding_year_location jsonb,
    ADD COLUMN funding_stage jsonb,
    ADD COLUMN platform_type_operator jsonb,
    ADD COLUMN sector_focus jsonb,
    ADD COLUMN platform_offerings jsonb,
    ADD COLUMN scale_indicator jsonb,
    ADD COLUMN investor_type_headquarters jsonb,
    ADD COLUMN sector_stage_focus jsonb,
    ADD COLUMN geographic_focus jsonb,
    ADD COLUMN published_fund_size jsonb,
    ADD COLUMN topic_investment_thesis jsonb,
    ADD COLUMN jurisdiction_parent_agency jsonb,
    ADD COLUMN topic_mandate_program jsonb,
    ADD COLUMN visible_funding_programs jsonb,
    ADD COLUMN mission_sector_focus jsonb,
    ADD COLUMN programs_grant_themes jsonb,
    ADD COLUMN association_type jsonb,
    ADD COLUMN sector_geographic_scope jsonb,
    ADD COLUMN member_types jsonb,
    ADD COLUMN linked_members jsonb,
    ADD COLUMN network_scope_locations jsonb,
    ADD COLUMN official_identity jsonb,
    ADD COLUMN parent_connection jsonb,
    ADD COLUMN sector_topic jsonb,
    ADD COLUMN hub_assignment jsonb,
    ADD COLUMN organization_category_type jsonb;

-- The data move: each organization's current values, unchanged.
UPDATE public.organization o SET
    primary_technical_focus = d.primary_technical_focus,
    technical_approach = d.technical_approach,
    current_activities = d.current_activities,
    funding_summary = d.funding_summary,
    location = d.location,
    why_matched = d.why_matched,
    recent_activity = d.recent_activity,
    funding_signal = d.funding_signal,
    international_connection = d.international_connection,
    um6p_ocp_connection = d.um6p_ocp_connection,
    current_initiative = d.current_initiative,
    current_initiative_working_group = d.current_initiative_working_group,
    current_project = d.current_project,
    pilot_customer_evidence = d.pilot_customer_evidence,
    relevant_program = d.relevant_program,
    topic_unit_and_work = d.topic_unit_and_work,
    institution_control = d.institution_control,
    land_grant_designation = d.land_grant_designation,
    rankings = d.rankings,
    relevant_centers_programs = d.relevant_centers_programs,
    parent_and_center_type = d.parent_and_center_type,
    topic_research_focus = d.topic_research_focus,
    active_recent_projects = d.active_recent_projects,
    main_funders = d.main_funders,
    sponsoring_agency = d.sponsoring_agency,
    formal_national_designation = d.formal_national_designation,
    topic_program_area = d.topic_program_area,
    facility_type_operator = d.facility_type_operator,
    testing_demonstration_scope = d.testing_demonstration_scope,
    clinical_research_focus = d.clinical_research_focus,
    parent_academic_link = d.parent_academic_link,
    hospital_type_scale = d.hospital_type_scale,
    ownership_and_size = d.ownership_and_size,
    topic_business_segment_product = d.topic_business_segment_product,
    mapped_geography_operations = d.mapped_geography_operations,
    technology_and_problem = d.technology_and_problem,
    founding_year_location = d.founding_year_location,
    funding_stage = d.funding_stage,
    platform_type_operator = d.platform_type_operator,
    sector_focus = d.sector_focus,
    platform_offerings = d.platform_offerings,
    scale_indicator = d.scale_indicator,
    investor_type_headquarters = d.investor_type_headquarters,
    sector_stage_focus = d.sector_stage_focus,
    geographic_focus = d.geographic_focus,
    published_fund_size = d.published_fund_size,
    topic_investment_thesis = d.topic_investment_thesis,
    jurisdiction_parent_agency = d.jurisdiction_parent_agency,
    topic_mandate_program = d.topic_mandate_program,
    visible_funding_programs = d.visible_funding_programs,
    mission_sector_focus = d.mission_sector_focus,
    programs_grant_themes = d.programs_grant_themes,
    association_type = d.association_type,
    sector_geographic_scope = d.sector_geographic_scope,
    member_types = d.member_types,
    linked_members = d.linked_members,
    network_scope_locations = d.network_scope_locations,
    official_identity = d.official_identity,
    parent_connection = d.parent_connection,
    sector_topic = d.sector_topic,
    hub_assignment = d.hub_assignment,
    organization_category_type = d.organization_category_type
FROM public.organization_details d
WHERE d.organization_id = o.organization_id;

DROP VIEW public.actor_details;
DROP VIEW public.organization_template;
DROP TABLE public.organization_details;

CREATE OR REPLACE FUNCTION public.ghus_organization_details_refresh(p_organization uuid, p_key text)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    v_value jsonb;
BEGIN
    -- 790: only the fact columns moved from organization_details are written here.
    IF NOT p_key = ANY (ARRAY[
            'primary_technical_focus',
            'technical_approach',
            'current_activities',
            'funding_summary',
            'location',
            'why_matched',
            'recent_activity',
            'funding_signal',
            'international_connection',
            'um6p_ocp_connection',
            'current_initiative',
            'current_initiative_working_group',
            'current_project',
            'pilot_customer_evidence',
            'relevant_program',
            'topic_unit_and_work',
            'institution_control',
            'land_grant_designation',
            'rankings',
            'relevant_centers_programs',
            'parent_and_center_type',
            'topic_research_focus',
            'active_recent_projects',
            'main_funders',
            'sponsoring_agency',
            'formal_national_designation',
            'topic_program_area',
            'facility_type_operator',
            'testing_demonstration_scope',
            'clinical_research_focus',
            'parent_academic_link',
            'hospital_type_scale',
            'ownership_and_size',
            'topic_business_segment_product',
            'mapped_geography_operations',
            'technology_and_problem',
            'founding_year_location',
            'funding_stage',
            'platform_type_operator',
            'sector_focus',
            'platform_offerings',
            'scale_indicator',
            'investor_type_headquarters',
            'sector_stage_focus',
            'geographic_focus',
            'published_fund_size',
            'topic_investment_thesis',
            'jurisdiction_parent_agency',
            'topic_mandate_program',
            'visible_funding_programs',
            'mission_sector_focus',
            'programs_grant_themes',
            'association_type',
            'sector_geographic_scope',
            'member_types',
            'linked_members',
            'network_scope_locations',
            'official_identity',
            'parent_connection',
            'sector_topic',
            'hub_assignment',
            'organization_category_type']) THEN
        RETURN;
    END IF;
    SELECT CASE WHEN f.collection_state = 'found' THEN f.fact_value
                ELSE to_jsonb(f.collection_state) END
      INTO v_value
      FROM organization_fact f
     WHERE f.organization_id = p_organization AND f.fact_key = p_key
       AND (EXISTS (SELECT 1 FROM organization_fact_current_pointer p
                     WHERE p.organization_fact_id = f.organization_fact_id)
            OR (f.topic_id IS NULL AND EXISTS (
                    SELECT 1 FROM organization_fact_current c
                     WHERE c.organization_fact_id = f.organization_fact_id
                       AND c.resolution_state = 'accepted')))
     ORDER BY (f.collection_state = 'found') DESC, f.retrieved_at DESC NULLS LAST,
              f.created_at DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    EXECUTE format('UPDATE public.organization SET %I = $1 WHERE organization_id = $2', p_key)
    USING v_value, p_organization;
END $fn$;

CREATE VIEW public.organization_template WITH (security_invoker = true) AS
 SELECT o.organization_id,
    o.name,
    array_to_string(o.alt_names, '; '::text) AS alternate_names,
    o.website,
    cat.display_name AS organization_category,
    COALESCE(ctype.display_name, o.category_type) AS category_type,
    o.category_note,
    o.description,
    sec.primary_sector,
    top.topic,
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
   FROM organization o
          LEFT JOIN organization_category_definition cat ON cat.category_code = o.organization_category
     LEFT JOIN organization_category_type_definition ctype ON ctype.category_code = o.organization_category AND ctype.type_code = o.category_type
     LEFT JOIN region_definition reg ON reg.region_code = o.region_code
     LEFT JOIN source src ON src.source_id = o.source_id
     LEFT JOIN LATERAL ( SELECT max(s.name::text) FILTER (WHERE os.is_primary) AS primary_sector,
            string_agg(s.name::text, '; '::text ORDER BY (s.name::text)) FILTER (WHERE NOT os.is_primary OR os.is_primary IS NULL) AS additional_sectors
           FROM organization_sector os
             JOIN sector s ON s.sector_id = os.sector_id
          WHERE os.organization_id = o.organization_id) sec ON true
     LEFT JOIN LATERAL ( SELECT string_agg(t.name, '; '::text ORDER BY t.name) AS topic
           FROM organization_topic ot
             JOIN topic t ON t.topic_id = ot.topic_id
          WHERE ot.organization_id = o.organization_id) top ON true
     LEFT JOIN LATERAL ( SELECT p.name AS parent_name,
            replace(e.relationship_type, '_'::text, ' '::text) AS parent_relationship
           FROM entity_edge e
             JOIN organization p ON p.organization_id = e.object_id
          WHERE e.subject_id = o.organization_id AND (e.subject_type = ANY (ARRAY['actor'::text, 'organization'::text])) AND (e.object_type = ANY (ARRAY['actor'::text, 'organization'::text])) AND (e.relationship_type = ANY (ARRAY['unit_of'::text, 'operated_by'::text]))
          ORDER BY e.created_at DESC
         LIMIT 1) par ON true
  WHERE o.merged_into_organization_id IS NULL;
COMMENT ON VIEW public.organization_template IS 'Organizations template (2026-11-12.1) as a view: one row per organization, template column order. Migration 730.';
COMMENT ON COLUMN public.organization_template.name IS 'Official name';
COMMENT ON COLUMN public.organization_template.alternate_names IS 'Other names';
COMMENT ON COLUMN public.organization_template.website IS 'Website';
COMMENT ON COLUMN public.organization_template.organization_category IS 'Organization Category';
COMMENT ON COLUMN public.organization_template.category_type IS 'Category Type';
COMMENT ON COLUMN public.organization_template.category_note IS 'Category note';
COMMENT ON COLUMN public.organization_template.description IS 'Description';
COMMENT ON COLUMN public.organization_template.primary_sector IS 'Sector';
COMMENT ON COLUMN public.organization_template.topic IS 'Topic';
COMMENT ON COLUMN public.organization_template.additional_sectors IS 'Additional sectors';
COMMENT ON COLUMN public.organization_template.city IS 'City';
COMMENT ON COLUMN public.organization_template.state_code IS 'State';
COMMENT ON COLUMN public.organization_template.region IS 'Region';
COMMENT ON COLUMN public.organization_template.country IS 'Country';
COMMENT ON COLUMN public.organization_template.parent_name IS 'Parent organization';
COMMENT ON COLUMN public.organization_template.parent_relationship IS 'Relationship to parent';
COMMENT ON COLUMN public.organization_template.source_url IS 'Source URL';
COMMENT ON COLUMN public.organization_template.recent_activity_date IS 'Recent activity date (no column of its own: empty)';
COMMENT ON COLUMN public.organization_template.ghus_notes IS 'GHUS Notes';
COMMENT ON COLUMN public.organization_template.um6p_ocp_connection IS 'UM6P/OCP connection';
COMMENT ON COLUMN public.organization_template.development_stage IS 'Startup: development stage (no column of its own: empty)';
REVOKE ALL ON public.organization_template FROM PUBLIC;
DO $roles$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON public.organization_template FROM %I', r);
        END IF;
    END LOOP;
END $roles$;

COMMIT;
