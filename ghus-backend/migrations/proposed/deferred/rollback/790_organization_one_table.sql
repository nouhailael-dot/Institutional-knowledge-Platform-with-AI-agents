-- Rollback 790: organization_details is rebuilt from the organization columns (its
-- other_facts and fact_sources come back empty: the readings are all in
-- organization_fact), the stand-in actor_details and the automatic copy come back as
-- before, and the 62 columns leave organization. Then:
-- DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '790';

BEGIN;
SET LOCAL lock_timeout = '15s';

DROP VIEW public.organization_template;

CREATE TABLE public.organization_details (
    organization_id uuid PRIMARY KEY REFERENCES public.organization(organization_id),
    primary_technical_focus jsonb,
    technical_approach jsonb,
    current_activities jsonb,
    funding_summary jsonb,
    location jsonb,
    why_matched jsonb,
    recent_activity jsonb,
    funding_signal jsonb,
    international_connection jsonb,
    um6p_ocp_connection jsonb,
    current_initiative jsonb,
    current_initiative_working_group jsonb,
    current_project jsonb,
    pilot_customer_evidence jsonb,
    relevant_program jsonb,
    topic_unit_and_work jsonb,
    institution_control jsonb,
    land_grant_designation jsonb,
    rankings jsonb,
    relevant_centers_programs jsonb,
    parent_and_center_type jsonb,
    topic_research_focus jsonb,
    active_recent_projects jsonb,
    main_funders jsonb,
    sponsoring_agency jsonb,
    formal_national_designation jsonb,
    topic_program_area jsonb,
    facility_type_operator jsonb,
    testing_demonstration_scope jsonb,
    clinical_research_focus jsonb,
    parent_academic_link jsonb,
    hospital_type_scale jsonb,
    ownership_and_size jsonb,
    topic_business_segment_product jsonb,
    mapped_geography_operations jsonb,
    technology_and_problem jsonb,
    founding_year_location jsonb,
    funding_stage jsonb,
    platform_type_operator jsonb,
    sector_focus jsonb,
    platform_offerings jsonb,
    scale_indicator jsonb,
    investor_type_headquarters jsonb,
    sector_stage_focus jsonb,
    geographic_focus jsonb,
    published_fund_size jsonb,
    topic_investment_thesis jsonb,
    jurisdiction_parent_agency jsonb,
    topic_mandate_program jsonb,
    visible_funding_programs jsonb,
    mission_sector_focus jsonb,
    programs_grant_themes jsonb,
    association_type jsonb,
    sector_geographic_scope jsonb,
    member_types jsonb,
    linked_members jsonb,
    network_scope_locations jsonb,
    official_identity jsonb,
    parent_connection jsonb,
    sector_topic jsonb,
    hub_assignment jsonb,
    organization_category_type jsonb,
    other_facts jsonb NOT NULL DEFAULT '{}'::jsonb,
    fact_sources jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.organization_details IS 'One row per organization, one column per box: the current reading of each box, kept by the database from actor_fact_current_pointer. Read-only for code; every reading with its source stays in actor_fact.';
ALTER TABLE public.organization_details ENABLE ROW LEVEL SECURITY;
INSERT INTO public.organization_details (organization_id, primary_technical_focus, technical_approach, current_activities, funding_summary, location, why_matched, recent_activity, funding_signal, international_connection, um6p_ocp_connection, current_initiative, current_initiative_working_group, current_project, pilot_customer_evidence, relevant_program, topic_unit_and_work, institution_control, land_grant_designation, rankings, relevant_centers_programs, parent_and_center_type, topic_research_focus, active_recent_projects, main_funders, sponsoring_agency, formal_national_designation, topic_program_area, facility_type_operator, testing_demonstration_scope, clinical_research_focus, parent_academic_link, hospital_type_scale, ownership_and_size, topic_business_segment_product, mapped_geography_operations, technology_and_problem, founding_year_location, funding_stage, platform_type_operator, sector_focus, platform_offerings, scale_indicator, investor_type_headquarters, sector_stage_focus, geographic_focus, published_fund_size, topic_investment_thesis, jurisdiction_parent_agency, topic_mandate_program, visible_funding_programs, mission_sector_focus, programs_grant_themes, association_type, sector_geographic_scope, member_types, linked_members, network_scope_locations, official_identity, parent_connection, sector_topic, hub_assignment, organization_category_type)
SELECT organization_id, primary_technical_focus, technical_approach, current_activities, funding_summary, location, why_matched, recent_activity, funding_signal, international_connection, um6p_ocp_connection, current_initiative, current_initiative_working_group, current_project, pilot_customer_evidence, relevant_program, topic_unit_and_work, institution_control, land_grant_designation, rankings, relevant_centers_programs, parent_and_center_type, topic_research_focus, active_recent_projects, main_funders, sponsoring_agency, formal_national_designation, topic_program_area, facility_type_operator, testing_demonstration_scope, clinical_research_focus, parent_academic_link, hospital_type_scale, ownership_and_size, topic_business_segment_product, mapped_geography_operations, technology_and_problem, founding_year_location, funding_stage, platform_type_operator, sector_focus, platform_offerings, scale_indicator, investor_type_headquarters, sector_stage_focus, geographic_focus, published_fund_size, topic_investment_thesis, jurisdiction_parent_agency, topic_mandate_program, visible_funding_programs, mission_sector_focus, programs_grant_themes, association_type, sector_geographic_scope, member_types, linked_members, network_scope_locations, official_identity, parent_connection, sector_topic, hub_assignment, organization_category_type FROM public.organization
 WHERE primary_technical_focus IS NOT NULL OR technical_approach IS NOT NULL OR current_activities IS NOT NULL OR funding_summary IS NOT NULL OR location IS NOT NULL OR why_matched IS NOT NULL OR recent_activity IS NOT NULL OR funding_signal IS NOT NULL OR international_connection IS NOT NULL OR um6p_ocp_connection IS NOT NULL OR current_initiative IS NOT NULL OR current_initiative_working_group IS NOT NULL OR current_project IS NOT NULL OR pilot_customer_evidence IS NOT NULL OR relevant_program IS NOT NULL OR topic_unit_and_work IS NOT NULL OR institution_control IS NOT NULL OR land_grant_designation IS NOT NULL OR rankings IS NOT NULL OR relevant_centers_programs IS NOT NULL OR parent_and_center_type IS NOT NULL OR topic_research_focus IS NOT NULL OR active_recent_projects IS NOT NULL OR main_funders IS NOT NULL OR sponsoring_agency IS NOT NULL OR formal_national_designation IS NOT NULL OR topic_program_area IS NOT NULL OR facility_type_operator IS NOT NULL OR testing_demonstration_scope IS NOT NULL OR clinical_research_focus IS NOT NULL OR parent_academic_link IS NOT NULL OR hospital_type_scale IS NOT NULL OR ownership_and_size IS NOT NULL OR topic_business_segment_product IS NOT NULL OR mapped_geography_operations IS NOT NULL OR technology_and_problem IS NOT NULL OR founding_year_location IS NOT NULL OR funding_stage IS NOT NULL OR platform_type_operator IS NOT NULL OR sector_focus IS NOT NULL OR platform_offerings IS NOT NULL OR scale_indicator IS NOT NULL OR investor_type_headquarters IS NOT NULL OR sector_stage_focus IS NOT NULL OR geographic_focus IS NOT NULL OR published_fund_size IS NOT NULL OR topic_investment_thesis IS NOT NULL OR jurisdiction_parent_agency IS NOT NULL OR topic_mandate_program IS NOT NULL OR visible_funding_programs IS NOT NULL OR mission_sector_focus IS NOT NULL OR programs_grant_themes IS NOT NULL OR association_type IS NOT NULL OR sector_geographic_scope IS NOT NULL OR member_types IS NOT NULL OR linked_members IS NOT NULL OR network_scope_locations IS NOT NULL OR official_identity IS NOT NULL OR parent_connection IS NOT NULL OR sector_topic IS NOT NULL OR hub_assignment IS NOT NULL OR organization_category_type IS NOT NULL;

CREATE OR REPLACE FUNCTION public.ghus_organization_details_refresh(p_organization uuid, p_key text)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_value jsonb;
    v_source jsonb;
    v_column boolean;
BEGIN
    SELECT CASE WHEN f.collection_state = 'found' THEN f.fact_value
                ELSE to_jsonb(f.collection_state) END,
           jsonb_strip_nulls(jsonb_build_object(
               'source_url', s.url, 'retrieved_at', f.retrieved_at,
               'confidence', f.confidence, 'topic_id', f.topic_id,
               'actor_fact_id', f.organization_fact_id))
      INTO v_value, v_source
      FROM organization_fact f
      LEFT JOIN source s ON s.source_id = f.source_id
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

    INSERT INTO organization_details (organization_id) VALUES (p_organization)
        ON CONFLICT (organization_id) DO NOTHING;

    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'organization_details'
                      AND column_name = p_key
                      AND column_name NOT IN ('organization_id', 'other_facts', 'fact_sources',
                                              'updated_at'))
      INTO v_column;

    IF v_column THEN
        EXECUTE format(
            'UPDATE organization_details SET %I = $1, fact_sources = fact_sources || $2, '
            'updated_at = now() WHERE organization_id = $3', p_key)
        USING v_value, jsonb_build_object(p_key, v_source), p_organization;
    ELSE
        UPDATE organization_details
           SET other_facts = other_facts || jsonb_build_object(p_key, v_value),
               fact_sources = fact_sources || jsonb_build_object(p_key, v_source),
               updated_at = now()
         WHERE organization_id = p_organization;
    END IF;
END $function$
;

CREATE VIEW public.actor_details WITH (security_invoker = true) AS
 SELECT organization_id AS actor_id,
    primary_technical_focus,
    technical_approach,
    current_activities,
    funding_summary,
    location,
    why_matched,
    recent_activity,
    funding_signal,
    international_connection,
    um6p_ocp_connection,
    current_initiative,
    current_initiative_working_group,
    current_project,
    pilot_customer_evidence,
    relevant_program,
    topic_unit_and_work,
    institution_control,
    land_grant_designation,
    rankings,
    relevant_centers_programs,
    parent_and_center_type,
    topic_research_focus,
    active_recent_projects,
    main_funders,
    sponsoring_agency,
    formal_national_designation,
    topic_program_area,
    facility_type_operator,
    testing_demonstration_scope,
    clinical_research_focus,
    parent_academic_link,
    hospital_type_scale,
    ownership_and_size,
    topic_business_segment_product,
    mapped_geography_operations,
    technology_and_problem,
    founding_year_location,
    funding_stage,
    platform_type_operator,
    sector_focus,
    platform_offerings,
    scale_indicator,
    investor_type_headquarters,
    sector_stage_focus,
    geographic_focus,
    published_fund_size,
    topic_investment_thesis,
    jurisdiction_parent_agency,
    topic_mandate_program,
    visible_funding_programs,
    mission_sector_focus,
    programs_grant_themes,
    association_type,
    sector_geographic_scope,
    member_types,
    linked_members,
    network_scope_locations,
    official_identity,
    parent_connection,
    sector_topic,
    hub_assignment,
    organization_category_type,
    other_facts,
    fact_sources,
    updated_at
   FROM organization_details;
COMMENT ON VIEW public.actor_details IS 'Stand-in for organization_details until the code uses the new name (migration 720).';

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
    d.recent_activity,
    NULL::text AS recent_activity_date,
    d.funding_signal,
    d.international_connection,
    d.primary_technical_focus,
    d.technical_approach,
    d.current_activities,
    d.funding_summary,
    o.ghus_notes,
    d.um6p_ocp_connection,
    d.topic_unit_and_work,
    d.institution_control,
    d.land_grant_designation,
    d.relevant_centers_programs,
    d.parent_and_center_type,
    d.topic_research_focus,
    d.active_recent_projects,
    d.main_funders,
    d.sponsoring_agency,
    d.formal_national_designation,
    d.topic_program_area,
    d.facility_type_operator,
    d.testing_demonstration_scope,
    d.current_project,
    d.clinical_research_focus,
    d.parent_academic_link,
    d.hospital_type_scale,
    d.current_initiative,
    d.ownership_and_size,
    d.topic_business_segment_product,
    d.mapped_geography_operations,
    NULL::text AS development_stage,
    d.technology_and_problem,
    d.founding_year_location,
    d.funding_stage,
    d.pilot_customer_evidence,
    d.platform_type_operator,
    d.sector_focus,
    d.platform_offerings,
    d.scale_indicator,
    d.investor_type_headquarters,
    d.sector_stage_focus,
    d.geographic_focus,
    d.published_fund_size,
    d.topic_investment_thesis,
    d.jurisdiction_parent_agency,
    d.topic_mandate_program,
    d.visible_funding_programs,
    d.mission_sector_focus,
    d.relevant_program,
    d.programs_grant_themes,
    d.association_type,
    d.sector_geographic_scope,
    d.member_types,
    d.current_initiative_working_group,
    d.linked_members,
    d.network_scope_locations,
    o.status
   FROM organization o
     LEFT JOIN organization_details d USING (organization_id)
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

ALTER TABLE public.organization
    DROP COLUMN primary_technical_focus,
    DROP COLUMN technical_approach,
    DROP COLUMN current_activities,
    DROP COLUMN funding_summary,
    DROP COLUMN location,
    DROP COLUMN why_matched,
    DROP COLUMN recent_activity,
    DROP COLUMN funding_signal,
    DROP COLUMN international_connection,
    DROP COLUMN um6p_ocp_connection,
    DROP COLUMN current_initiative,
    DROP COLUMN current_initiative_working_group,
    DROP COLUMN current_project,
    DROP COLUMN pilot_customer_evidence,
    DROP COLUMN relevant_program,
    DROP COLUMN topic_unit_and_work,
    DROP COLUMN institution_control,
    DROP COLUMN land_grant_designation,
    DROP COLUMN rankings,
    DROP COLUMN relevant_centers_programs,
    DROP COLUMN parent_and_center_type,
    DROP COLUMN topic_research_focus,
    DROP COLUMN active_recent_projects,
    DROP COLUMN main_funders,
    DROP COLUMN sponsoring_agency,
    DROP COLUMN formal_national_designation,
    DROP COLUMN topic_program_area,
    DROP COLUMN facility_type_operator,
    DROP COLUMN testing_demonstration_scope,
    DROP COLUMN clinical_research_focus,
    DROP COLUMN parent_academic_link,
    DROP COLUMN hospital_type_scale,
    DROP COLUMN ownership_and_size,
    DROP COLUMN topic_business_segment_product,
    DROP COLUMN mapped_geography_operations,
    DROP COLUMN technology_and_problem,
    DROP COLUMN founding_year_location,
    DROP COLUMN funding_stage,
    DROP COLUMN platform_type_operator,
    DROP COLUMN sector_focus,
    DROP COLUMN platform_offerings,
    DROP COLUMN scale_indicator,
    DROP COLUMN investor_type_headquarters,
    DROP COLUMN sector_stage_focus,
    DROP COLUMN geographic_focus,
    DROP COLUMN published_fund_size,
    DROP COLUMN topic_investment_thesis,
    DROP COLUMN jurisdiction_parent_agency,
    DROP COLUMN topic_mandate_program,
    DROP COLUMN visible_funding_programs,
    DROP COLUMN mission_sector_focus,
    DROP COLUMN programs_grant_themes,
    DROP COLUMN association_type,
    DROP COLUMN sector_geographic_scope,
    DROP COLUMN member_types,
    DROP COLUMN linked_members,
    DROP COLUMN network_scope_locations,
    DROP COLUMN official_identity,
    DROP COLUMN parent_connection,
    DROP COLUMN sector_topic,
    DROP COLUMN hub_assignment,
    DROP COLUMN organization_category_type;

REVOKE ALL ON public.actor_details, public.organization_template FROM PUBLIC;
DO $roles$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON public.actor_details, public.organization_template FROM %I', r);
            EXECUTE format('GRANT ALL ON public.organization_details TO %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON public.actor_details TO service_role;
    END IF;
END $roles$;

COMMIT;
