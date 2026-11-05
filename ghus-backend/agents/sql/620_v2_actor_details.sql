-- Architecture V2 - one row per organization with a column for every box.
--
-- Decision (2026-11-05, platform owner): every box Review shows and every
-- field an Explore and Map card shows needs a visible place in the database.
--
-- Until now the boxes lived only as rows of actor_fact (one row per reading,
-- with its source, origin, confidence and date read). actor_fact stays the
-- record of every reading: Architecture V2 section 5.1 asks for sources and
-- confidence on every fact, and section 6 for "never overwrite, never delete".
--
-- actor_details holds the organization's current value of each box, one column
-- per box, kept up to date by the database itself: whenever a box's current
-- reading changes (actor_fact_current_pointer), its column is refreshed. No
-- code writes it. A box read and not found holds "not_found" (standing rule 7).
-- A reading with no column of its own goes to other_facts, so nothing is
-- dropped; fact_sources gives, per box, the page, date read and confidence.
-- When an organization has the same box under several topics, the newest
-- found reading wins.
--
-- People's GHUS Notes alter a canonical table, so they are in the schema
-- owner's track: migrations/proposed/deferred/625_v2_person_ghus_notes.sql.
--
-- Columns generated from the agents' own box lists (light_pull.py,
-- light_pull_reader.py, fact_parts.py) and the Explore and Map card schema.
-- ORDERING: after 610. Additive only: no existing column or row changes.
-- ROLLBACK: agents/sql/rollback/620_v2_actor_details.sql
-- Local isolated test databases first. Production needs the platform owner's
-- approval, a fresh backup and a ledger entry.

BEGIN;

-- ---------------------------------------------------------------------------
-- actor_details: a column for every box
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actor_details (
    actor_id uuid PRIMARY KEY REFERENCES actor(actor_id),
    -- Profile boxes Review shows and edits
    primary_technical_focus jsonb,
    technical_approach jsonb,
    current_activities jsonb,
    technology_ip_notes jsonb,
    key_constraints jsonb,
    funding_summary jsonb,
    estimated_trl jsonb,
    primary_lifecycle_role jsonb,
    -- Summaries carried over from V1
    identity_summary jsonb,
    profile_summary jsonb,
    technical_summary jsonb,
    lifecycle_summary jsonb,
    -- Light Pull boxes every organization has
    location jsonb,
    why_matched jsonb,
    recent_activity jsonb,
    funding_signal jsonb,
    international_connection jsonb,
    um6p_ocp_connection jsonb,
    -- List boxes (newest entry first)
    current_initiative jsonb,
    current_initiative_working_group jsonb,
    current_project jsonb,
    pilot_customer_evidence jsonb,
    relevant_program jsonb,
    -- Category-specific boxes
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
    published_stage_or_trl jsonb,
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
    -- Identity and placement facts
    official_identity jsonb,
    parent_connection jsonb,
    sector_topic jsonb,
    hub_assignment jsonb,
    actor_category_type jsonb,
    -- Explore and Map card fields
    category_details jsonb,
    actor_relationships jsonb,
    international_connections jsonb,
    match_explanation jsonb,
    match_strength jsonb,
    multi_location jsonb,
    mapped_topic jsonb,
    people jsonb,
    -- Any other reading, by its box name: nothing is dropped.
    other_facts jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Per box: source_url, retrieved_at, confidence, topic_id, actor_fact_id.
    fact_sources jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE actor_details IS
    'One row per organization, one column per box: the current reading of each '
    'box, kept by the database from actor_fact_current_pointer. Read-only for '
    'code; every reading with its source stays in actor_fact.';

CREATE OR REPLACE FUNCTION ghus_actor_details_refresh(p_actor uuid, p_key text)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    v_value jsonb;
    v_source jsonb;
BEGIN
    SELECT CASE WHEN f.collection_state = 'found' THEN f.fact_value
                ELSE to_jsonb(f.collection_state) END,
           jsonb_strip_nulls(jsonb_build_object(
               'source_url', s.url, 'retrieved_at', f.retrieved_at,
               'confidence', f.confidence, 'topic_id', f.topic_id,
               'actor_fact_id', f.actor_fact_id))
      INTO v_value, v_source
      FROM actor_fact_current_pointer p
      JOIN actor_fact f ON f.actor_fact_id = p.actor_fact_id
      LEFT JOIN source s ON s.source_id = f.source_id
     WHERE p.actor_id = p_actor AND p.fact_key = p_key
     ORDER BY (f.collection_state = 'found') DESC, f.retrieved_at DESC NULLS LAST,
              f.created_at DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO actor_details (actor_id) VALUES (p_actor) ON CONFLICT (actor_id) DO NOTHING;

    IF p_key = ANY (ARRAY[
        'primary_technical_focus',
        'technical_approach',
        'current_activities',
        'technology_ip_notes',
        'key_constraints',
        'funding_summary',
        'estimated_trl',
        'primary_lifecycle_role',
        'identity_summary',
        'profile_summary',
        'technical_summary',
        'lifecycle_summary',
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
        'published_stage_or_trl',
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
        'actor_category_type',
        'category_details',
        'actor_relationships',
        'international_connections',
        'match_explanation',
        'match_strength',
        'multi_location',
        'mapped_topic',
        'people'
    ]) THEN
        EXECUTE format(
            'UPDATE actor_details SET %I = $1, fact_sources = fact_sources || $2, '
            'updated_at = now() WHERE actor_id = $3', p_key)
        USING v_value, jsonb_build_object(p_key, v_source), p_actor;
    ELSE
        UPDATE actor_details
           SET other_facts = other_facts || jsonb_build_object(p_key, v_value),
               fact_sources = fact_sources || jsonb_build_object(p_key, v_source),
               updated_at = now()
         WHERE actor_id = p_actor;
    END IF;
END $fn$;

CREATE OR REPLACE FUNCTION ghus_actor_details_on_pointer() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    PERFORM ghus_actor_details_refresh(NEW.actor_id, NEW.fact_key);
    RETURN NULL;
END $fn$;

DROP TRIGGER IF EXISTS actor_details_follows_pointer ON actor_fact_current_pointer;
CREATE TRIGGER actor_details_follows_pointer
    AFTER INSERT OR UPDATE ON actor_fact_current_pointer
    FOR EACH ROW EXECUTE FUNCTION ghus_actor_details_on_pointer();

-- Fill it from every current reading already recorded.
DO $fill$
DECLARE r record;
BEGIN
    FOR r IN SELECT DISTINCT actor_id, fact_key FROM actor_fact_current_pointer LOOP
        PERFORM ghus_actor_details_refresh(r.actor_id, r.fact_key);
    END LOOP;
END $fill$;

ALTER TABLE actor_details ENABLE ROW LEVEL SECURITY;

COMMIT;
