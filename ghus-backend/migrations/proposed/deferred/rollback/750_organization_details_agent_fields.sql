-- Rollback 750: the 16 organization_details columns come back EMPTY and the views as
-- they were. The deleted values are in the backup taken before 750; the 620 refresh
-- (ghus_actor_details_refresh) can refill a column from the facts, which 750 never touched.
-- Then: DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '750';

BEGIN;
SET LOCAL lock_timeout = '15s';
DROP VIEW public.actor_read;
DROP VIEW public.actor_details;
DROP VIEW public.organization_template;
DROP VIEW public.organization_read;

ALTER TABLE public.organization_details
    ADD COLUMN technology_ip_notes jsonb,
    ADD COLUMN key_constraints jsonb,
    ADD COLUMN estimated_trl jsonb,
    ADD COLUMN primary_lifecycle_role jsonb,
    ADD COLUMN identity_summary jsonb,
    ADD COLUMN profile_summary jsonb,
    ADD COLUMN technical_summary jsonb,
    ADD COLUMN lifecycle_summary jsonb,
    ADD COLUMN category_details jsonb,
    ADD COLUMN organization_relationships jsonb,
    ADD COLUMN international_connections jsonb,
    ADD COLUMN match_explanation jsonb,
    ADD COLUMN match_strength jsonb,
    ADD COLUMN multi_location jsonb,
    ADD COLUMN mapped_topic jsonb,
    ADD COLUMN people jsonb;

CREATE VIEW public.organization_read AS
 SELECT a.organization_id,
    a.name,
    a.slug,
    a.organization_category,
    a.category_type,
    a.category_note,
    a.category_needs_review,
    a.description,
    a.website,
    a.website_domain,
    a.city,
    a.state_code,
    a.region_code,
    a.country,
    a.latitude,
    a.longitude,
    a.is_multi_location,
    a.status,
    a.source_origin,
    a.source_id,
    a.merged_into_organization_id,
    a.alt_names,
    a.created_at,
    a.updated_at,
    f.primary_technical_focus,
    f.technical_approach,
    f.current_activities,
    f.technology_ip_notes,
    f.key_constraints,
    f.funding_summary,
    f.estimated_trl::smallint AS estimated_trl,
    f.primary_lifecycle_role
   FROM organization a
     LEFT JOIN LATERAL ( SELECT max(organization_fact.fact_value #>> '{}'::text[]) FILTER (WHERE organization_fact.fact_key = 'primary_technical_focus'::text) AS primary_technical_focus,
            max(organization_fact.fact_value #>> '{}'::text[]) FILTER (WHERE organization_fact.fact_key = 'technical_approach'::text) AS technical_approach,
            max(organization_fact.fact_value #>> '{}'::text[]) FILTER (WHERE organization_fact.fact_key = 'current_activities'::text) AS current_activities,
            max(organization_fact.fact_value #>> '{}'::text[]) FILTER (WHERE organization_fact.fact_key = 'technology_ip_notes'::text) AS technology_ip_notes,
            max(organization_fact.fact_value #>> '{}'::text[]) FILTER (WHERE organization_fact.fact_key = 'key_constraints'::text) AS key_constraints,
            max(organization_fact.fact_value #>> '{}'::text[]) FILTER (WHERE organization_fact.fact_key = 'funding_summary'::text) AS funding_summary,
            max(organization_fact.fact_value #>> '{}'::text[]) FILTER (WHERE organization_fact.fact_key = 'estimated_trl'::text) AS estimated_trl,
            max(organization_fact.fact_value #>> '{}'::text[]) FILTER (WHERE organization_fact.fact_key = 'primary_lifecycle_role'::text) AS primary_lifecycle_role
           FROM organization_fact
          WHERE organization_fact.organization_id = a.organization_id AND organization_fact.fact_type = 'legacy_baseline'::text) f ON true
  WHERE a.status IS DISTINCT FROM 'rejected'::text AND NOT (EXISTS ( SELECT 1
           FROM compass.deleted_record d
          WHERE d.entity_type = 'actor'::text AND d.entity_id = a.organization_id AND d.restored_at IS NULL AND d.purged_at IS NULL));
COMMENT ON VIEW public.organization_read IS 'Architecture V2 application read surface; stable across migration 500.';
CREATE VIEW public.actor_read WITH (security_invoker = true) AS
 SELECT organization_id AS actor_id,
    name,
    slug,
    organization_category AS actor_category,
    category_type,
    category_note,
    category_needs_review,
    description,
    website,
    website_domain,
    city,
    state_code,
    region_code,
    country,
    latitude,
    longitude,
    is_multi_location,
    status,
    source_origin,
    source_id,
    merged_into_organization_id AS merged_into_actor_id,
    alt_names,
    created_at,
    updated_at,
    primary_technical_focus,
    technical_approach,
    current_activities,
    technology_ip_notes,
    key_constraints,
    funding_summary,
    estimated_trl,
    primary_lifecycle_role
   FROM organization_read;
COMMENT ON VIEW public.actor_read IS 'Stand-in for organization_read until the code uses the new name (migration 720).';
CREATE VIEW public.actor_details WITH (security_invoker = true) AS
 SELECT organization_id AS actor_id,
    primary_technical_focus,
    technical_approach,
    current_activities,
    technology_ip_notes,
    key_constraints,
    funding_summary,
    estimated_trl,
    primary_lifecycle_role,
    identity_summary,
    profile_summary,
    technical_summary,
    lifecycle_summary,
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
    published_stage_or_trl,
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
    organization_category_type AS actor_category_type,
    category_details,
    organization_relationships AS actor_relationships,
    international_connections,
    match_explanation,
    match_strength,
    multi_location,
    mapped_topic,
    people,
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
    d.technology_ip_notes,
    d.key_constraints,
    d.funding_summary,
    d.primary_lifecycle_role,
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

REVOKE ALL ON public.organization_read, public.actor_read, public.actor_details,
              public.organization_template FROM PUBLIC;
DO $roles$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON public.actor_read, public.actor_details, public.organization_template FROM %I', r);
            EXECUTE format('GRANT ALL ON public.organization_read TO %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON public.actor_read, public.actor_details TO service_role;
    END IF;
END $roles$;
COMMIT;
