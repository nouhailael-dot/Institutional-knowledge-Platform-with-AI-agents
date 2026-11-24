-- 770: the startup "Stage or TRL" column goes (GHUS, 24 Nov 2026: TRL is removed from
-- the project).
--
--   * Deletes public.organization_details.published_stage_or_trl (67 -> 66 columns). On
--     24 Nov it held 2 values, both "not_found" (Veolia North America, Breakthrough
--     Energy Ventures); no reading is lost: they stay in organization_fact.
--   * Recreates the 720 stand-in actor_details without it, with the same comment,
--     option (security_invoker) and access (service_role only).
--   * A startup keeps its development stage, a separate field ("Startup: development
--     stage" in the Organizations template). Until the update agent stops collecting
--     published_stage_or_trl, what it reads goes to other_facts (620/621), never an error.
--
-- One transaction: any failure changes nothing. Rollback:
-- deferred/rollback/770_drop_published_stage_or_trl.sql

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '750') THEN
        RAISE EXCEPTION '770 refused: migration 750 is not applied';
    END IF;
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '770') THEN
        RAISE EXCEPTION '770 refused: already in the ledger';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                     AND table_name = 'organization_details' AND column_name = 'published_stage_or_trl') THEN
        RAISE EXCEPTION '770 refused: organization_details has no published_stage_or_trl';
    END IF;
END $guard$;

DROP VIEW public.actor_details;

ALTER TABLE public.organization_details DROP COLUMN published_stage_or_trl;

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

DO $roles$
DECLARE r text;
BEGIN
    REVOKE ALL ON public.actor_details FROM PUBLIC;
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON public.actor_details FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON public.actor_details TO service_role;
    END IF;
END $roles$;

COMMIT;
