-- 730: the Organizations template as a database view (GHUS, 23-24 Nov 2026:
-- "database columns = templates, same order").
--
--   * Adds one read-only view, public.organization_template: one row per organization
--     (merged records left out), its columns in the order of the Organizations
--     template (src/datafeed/contract.py ACTOR_FIELDS, template 2026-11-12.1), named
--     by the template's field keys, each column commented with the template header.
--   * Labels, not codes: category, category type and region read as the template
--     writes them. Sectors and topics come from their own tables.
--   * Two template fields have no column of their own and read empty (never guessed):
--     recent_activity_date (inside the recent-activity fact) and development_stage
--     (classification evidence).
--   * organization_id first and status last, so a row can be traced and filtered.
--   * Nothing else changes: no table, column or row is written.
--   * Like the 720 stand-ins, it runs with the caller's rights (security_invoker) and
--     Supabase's public roles anon and authenticated have no access to it.
--
-- One transaction: any failure changes nothing.

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '720') THEN
        RAISE EXCEPTION '730 refused: migration 720 (organization names) is not applied';
    END IF;
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '730') THEN
        RAISE EXCEPTION '730 refused: already in the ledger';
    END IF;
    IF to_regclass('public.organization_template') IS NOT NULL THEN
        RAISE EXCEPTION '730 refused: public.organization_template already exists';
    END IF;
END $guard$;

CREATE VIEW public.organization_template WITH (security_invoker = true) AS
SELECT
    o.organization_id,
    o.name,
    array_to_string(o.alt_names, '; ')                          AS alternate_names,
    o.website,
    cat.display_name                                            AS organization_category,
    COALESCE(ctype.display_name, o.category_type)               AS category_type,
    o.category_note,
    o.description,
    sec.primary_sector,
    top.topic,
    sec.additional_sectors,
    o.city,
    o.state_code,
    reg.display_name                                            AS region,
    o.country,
    par.parent_name,
    par.parent_relationship,
    src.url                                                     AS source_url,
    d.recent_activity,
    NULL::text                                                  AS recent_activity_date,
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
    NULL::text                                                  AS development_stage,
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
FROM public.organization o
LEFT JOIN public.organization_details d USING (organization_id)
LEFT JOIN public.organization_category_definition cat
       ON cat.category_code = o.organization_category
LEFT JOIN public.organization_category_type_definition ctype
       ON ctype.category_code = o.organization_category AND ctype.type_code = o.category_type
LEFT JOIN public.region_definition reg ON reg.region_code = o.region_code
LEFT JOIN public.source src ON src.source_id = o.source_id
LEFT JOIN LATERAL (
    SELECT max(s.name) FILTER (WHERE os.is_primary)                           AS primary_sector,
           string_agg(s.name, '; ' ORDER BY s.name) FILTER (WHERE NOT os.is_primary
                                                              OR os.is_primary IS NULL) AS additional_sectors
    FROM public.organization_sector os
    JOIN public.sector s ON s.sector_id = os.sector_id
    WHERE os.organization_id = o.organization_id
) sec ON true
LEFT JOIN LATERAL (
    SELECT string_agg(t.name, '; ' ORDER BY t.name) AS topic
    FROM public.organization_topic ot
    JOIN public.topic t ON t.topic_id = ot.topic_id
    WHERE ot.organization_id = o.organization_id
) top ON true
LEFT JOIN LATERAL (
    SELECT p.name AS parent_name, replace(e.relationship_type, '_', ' ') AS parent_relationship
    FROM public.entity_edge e
    JOIN public.organization p ON p.organization_id = e.object_id
    WHERE e.subject_id = o.organization_id
      AND e.subject_type IN ('actor', 'organization')
      AND e.object_type IN ('actor', 'organization')
      AND e.relationship_type IN ('unit_of', 'operated_by')
    ORDER BY e.created_at DESC
    LIMIT 1
) par ON true
WHERE o.merged_into_organization_id IS NULL;

COMMENT ON VIEW public.organization_template IS
    'Organizations template (2026-11-12.1) as a view: one row per organization, template column order. Migration 730.';
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
COMMENT ON COLUMN public.organization_template.development_stage IS 'Startup: development stage (no column of its own: empty)';
COMMENT ON COLUMN public.organization_template.ghus_notes IS 'GHUS Notes';
COMMENT ON COLUMN public.organization_template.um6p_ocp_connection IS 'UM6P/OCP connection';

REVOKE ALL ON public.organization_template FROM PUBLIC;
DO $roles$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON public.organization_template FROM anon';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON public.organization_template FROM authenticated';
    END IF;
END $roles$;

COMMIT;
