-- Rollback 800: the organization names and the actor stand-ins come back exactly as they were.
-- Run in the SQL editor, then: DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '800';
-- The data is untouched; only names, functions and the stand-in views change.

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM compass.migration_snapshot WHERE migration_id = '800') THEN
        RAISE EXCEPTION 'rollback 800 refused: no snapshot of 800 (it was not applied here)';
    END IF;
END $guard$;

-- Functions: the actor-named ones (and their triggers) go; the saved definitions return.
CREATE TEMP TABLE _fn_triggers ON COMMIT DROP AS
SELECT tg.tgname, c.relname, pg_get_triggerdef(tg.oid) AS def
  FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid JOIN pg_proc p ON p.oid = tg.tgfoid
 WHERE NOT tg.tgisinternal AND p.pronamespace = 'public'::regnamespace AND p.proname = ANY ('{ghus_actor_details_on_pointer,ghus_actor_details_on_topicless_fact,ghus_actor_details_refresh,ghus_guard_actor_status,ghus_prevent_actor_family_cycle,ghus_project_actor_verification_status}'::text[]);
DO $drop_triggers$
DECLARE t record;
BEGIN
    FOR t IN SELECT * FROM _fn_triggers LOOP
        EXECUTE format('DROP TRIGGER %I ON public.%I', t.tgname, t.relname);
    END LOOP;
END $drop_triggers$;
DROP FUNCTION public.ghus_guard_actor_status();
DROP FUNCTION public.ghus_actor_details_on_pointer();
DROP FUNCTION public.ghus_actor_details_on_topicless_fact();
DROP FUNCTION public.ghus_actor_details_refresh(p_organization uuid, p_key text);
DROP FUNCTION public.ghus_prevent_actor_family_cycle();
DROP FUNCTION public.ghus_project_actor_verification_status();

-- Names back first (the saved function bodies use them).
DO $names$
DECLARE x record; parts text[];
BEGIN
    FOR x IN SELECT object_name, definition FROM compass.migration_snapshot
              WHERE migration_id = '800'
                AND split_part(object_name, ':', 2) IN ('constraint', 'index', 'trigger', 'policy') LOOP
        parts := string_to_array(x.object_name, ':');
        CASE parts[2]
            WHEN 'constraint' THEN EXECUTE format('ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I', parts[3], x.definition, parts[4]);
            WHEN 'index' THEN EXECUTE format('ALTER INDEX public.%I RENAME TO %I', x.definition, parts[4]);
            WHEN 'trigger' THEN
                -- Triggers on the re-created functions were dropped above; they return below.
                IF EXISTS (SELECT 1 FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid
                            WHERE c.relnamespace = 'public'::regnamespace AND c.relname = parts[3]
                              AND tg.tgname = x.definition) THEN
                    EXECUTE format('ALTER TRIGGER %I ON public.%I RENAME TO %I', x.definition, parts[3], parts[4]);
                END IF;
            WHEN 'policy' THEN EXECUTE format('ALTER POLICY %I ON public.%I RENAME TO %I', x.definition, parts[3], parts[4]);
        END CASE;
    END LOOP;
END $names$;

ALTER TABLE public.hub_actor RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.hub_actor_removed RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor RENAME COLUMN merged_into_actor_id TO merged_into_organization_id;
ALTER TABLE public.actor RENAME COLUMN actor_category TO organization_category;
ALTER TABLE public.actor RENAME COLUMN actor_category_type TO organization_category_type;
ALTER TABLE public.actor_category_migration_audit RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_evaluation RENAME COLUMN actor_evaluation_id TO organization_evaluation_id;
ALTER TABLE public.actor_evaluation RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_fact RENAME COLUMN actor_fact_id TO organization_fact_id;
ALTER TABLE public.actor_fact RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_fact_current_pointer RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_fact_current_pointer RENAME COLUMN actor_fact_id TO organization_fact_id;
ALTER TABLE public.actor_location RENAME COLUMN actor_location_id TO organization_location_id;
ALTER TABLE public.actor_location RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_merge_log RENAME COLUMN winner_actor_id TO winner_organization_id;
ALTER TABLE public.actor_merge_log RENAME COLUMN loser_actor_id TO loser_organization_id;
ALTER TABLE public.actor_person RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_ranking RENAME COLUMN actor_ranking_id TO organization_ranking_id;
ALTER TABLE public.actor_ranking RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_ranking RENAME COLUMN context_actor_id TO context_organization_id;
ALTER TABLE public.actor_relevance RENAME COLUMN actor_relevance_id TO organization_relevance_id;
ALTER TABLE public.actor_relevance RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_sector RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_strategic_connection_check RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_topic RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_update_subscription RENAME COLUMN actor_update_subscription_id TO organization_update_subscription_id;
ALTER TABLE public.actor_update_subscription RENAME COLUMN actor_ids TO organization_ids;
ALTER TABLE public.actor_update_subscription RENAME COLUMN max_new_actors_per_run TO max_new_organizations_per_run;
ALTER TABLE public.actor_update_subscription_run RENAME COLUMN actor_update_subscription_id TO organization_update_subscription_id;
ALTER TABLE public.actor_verification_event RENAME COLUMN actor_verification_event_id TO organization_verification_event_id;
ALTER TABLE public.actor_verification_event RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_descendant_edge RENAME COLUMN root_actor_id TO root_organization_id;
ALTER TABLE public.actor_descendant_edge RENAME COLUMN descendant_actor_id TO descendant_organization_id;
ALTER TABLE public.actor_descendants RENAME COLUMN root_actor_id TO root_organization_id;
ALTER TABLE public.actor_descendants RENAME COLUMN descendant_actor_id TO descendant_organization_id;
ALTER TABLE public.actor_fact_current RENAME COLUMN actor_fact_id TO organization_fact_id;
ALTER TABLE public.actor_fact_current RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_fact_current_v2 RENAME COLUMN actor_fact_id TO organization_fact_id;
ALTER TABLE public.actor_fact_current_v2 RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_fact_history RENAME COLUMN actor_fact_id TO organization_fact_id;
ALTER TABLE public.actor_fact_history RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_read RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_read RENAME COLUMN actor_category TO organization_category;
ALTER TABLE public.actor_read RENAME COLUMN merged_into_actor_id TO merged_into_organization_id;
ALTER TABLE public.actor_template RENAME COLUMN actor_id TO organization_id;
ALTER TABLE public.actor_template RENAME COLUMN actor_category TO organization_category;
ALTER VIEW public.actor_descendant_edge RENAME TO organization_descendant_edge;
ALTER VIEW public.actor_descendants RENAME TO organization_descendants;
ALTER VIEW public.actor_fact_current RENAME TO organization_fact_current;
ALTER VIEW public.actor_fact_current_v2 RENAME TO organization_fact_current_v2;
ALTER VIEW public.actor_fact_history RENAME TO organization_fact_history;
ALTER VIEW public.actor_read RENAME TO organization_read;
ALTER VIEW public.actor_template RENAME TO organization_template;
ALTER TABLE public.hub_actor RENAME TO hub_organization;
ALTER TABLE public.hub_actor_removed RENAME TO hub_organization_removed;
ALTER TABLE public.actor RENAME TO organization;
ALTER TABLE public.actor_category_definition RENAME TO organization_category_definition;
ALTER TABLE public.actor_category_migration_audit RENAME TO organization_category_migration_audit;
ALTER TABLE public.actor_category_type_definition RENAME TO organization_category_type_definition;
ALTER TABLE public.actor_evaluation RENAME TO organization_evaluation;
ALTER TABLE public.actor_fact RENAME TO organization_fact;
ALTER TABLE public.actor_fact_current_pointer RENAME TO organization_fact_current_pointer;
ALTER TABLE public.actor_location RENAME TO organization_location;
ALTER TABLE public.actor_merge_log RENAME TO organization_merge_log;
ALTER TABLE public.actor_person RENAME TO organization_person;
ALTER TABLE public.actor_ranking RENAME TO organization_ranking;
ALTER TABLE public.actor_relevance RENAME TO organization_relevance;
ALTER TABLE public.actor_sector RENAME TO organization_sector;
ALTER TABLE public.actor_strategic_connection_check RENAME TO organization_strategic_connection_check;
ALTER TABLE public.actor_topic RENAME TO organization_topic;
ALTER TABLE public.actor_update_subscription RENAME TO organization_update_subscription;
ALTER TABLE public.actor_update_subscription_run RENAME TO organization_update_subscription_run;
ALTER TABLE public.actor_verification_event RENAME TO organization_verification_event;

DO $restore$
DECLARE d record;
BEGIN
    FOR d IN SELECT definition FROM compass.migration_snapshot
              WHERE migration_id = '800' AND object_name LIKE 'function:%' LOOP
        EXECUTE d.definition;
    END LOOP;
END $restore$;
DO $make_triggers$
DECLARE t record;
BEGIN
    FOR t IN SELECT * FROM _fn_triggers LOOP
        -- Trigger, table and function names all said organization before 800.
        EXECUTE replace(t.def, 'actor', 'organization');
    END LOOP;
END $make_triggers$;

-- The stand-ins, as they were.
CREATE VIEW public.actor WITH (security_invoker=true) AS
 SELECT organization_id AS actor_id,
    name,
    slug,
    description,
    website,
    city,
    country,
    source_id,
    confidence,
    created_at,
    updated_at,
    merged_into_organization_id AS merged_into_actor_id,
    organization_category AS actor_category,
    alt_names,
    category_type,
    category_note,
    category_needs_review,
    website_domain,
    state_code,
    region_code,
    latitude,
    longitude,
    is_multi_location,
    source_origin,
    ghus_notes,
    status
   FROM organization;
COMMENT ON VIEW public.actor IS 'Stand-in for organization until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor TO service_role;
CREATE VIEW public.actor_category_definition WITH (security_invoker=true) AS
 SELECT category_code,
    display_name,
    description,
    sort_order,
    active
   FROM organization_category_definition;
COMMENT ON VIEW public.actor_category_definition IS 'Stand-in for organization_category_definition until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_category_definition FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_category_definition TO service_role;
CREATE VIEW public.actor_category_migration_audit WITH (security_invoker=true) AS
 SELECT organization_id AS actor_id,
    migration_batch_id,
    legacy_category,
    legacy_category_raw,
    mapped_category,
    mapping_status,
    prior_status,
    prior_source_origin,
    prior_category_note,
    prior_category_needs_review,
    migrated_at
   FROM organization_category_migration_audit;
COMMENT ON VIEW public.actor_category_migration_audit IS 'Stand-in for organization_category_migration_audit until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_category_migration_audit FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_category_migration_audit TO service_role;
CREATE VIEW public.actor_category_type_definition WITH (security_invoker=true) AS
 SELECT category_code,
    type_code,
    display_name,
    sort_order,
    active,
    definition,
    is_other
   FROM organization_category_type_definition;
COMMENT ON VIEW public.actor_category_type_definition IS 'Stand-in for organization_category_type_definition until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_category_type_definition FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_category_type_definition TO service_role;
CREATE VIEW public.actor_descendant_edge WITH (security_invoker=true) AS
 SELECT root_organization_id AS root_actor_id,
    descendant_organization_id AS descendant_actor_id,
    depth,
    path
   FROM organization_descendant_edge;
COMMENT ON VIEW public.actor_descendant_edge IS 'Stand-in for organization_descendant_edge until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_descendant_edge FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_descendant_edge TO service_role;
CREATE VIEW public.actor_descendants WITH (security_invoker=true) AS
 SELECT root_organization_id AS root_actor_id,
    descendant_organization_id AS descendant_actor_id,
    depth,
    path
   FROM organization_descendants;
COMMENT ON VIEW public.actor_descendants IS 'Stand-in for organization_descendants until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_descendants FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_descendants TO service_role;
CREATE VIEW public.actor_evaluation WITH (security_invoker=true) AS
 SELECT organization_evaluation_id AS actor_evaluation_id,
    organization_id AS actor_id,
    evaluation_context,
    context_entity_type,
    context_entity_id,
    score,
    evaluation_summary,
    evidence_summary,
    source_id,
    verification_status,
    confidence,
    generated_by,
    created_at,
    updated_at
   FROM organization_evaluation;
COMMENT ON VIEW public.actor_evaluation IS 'Stand-in for organization_evaluation until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_evaluation FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_evaluation TO service_role;
CREATE VIEW public.actor_fact WITH (security_invoker=true) AS
 SELECT organization_fact_id AS actor_fact_id,
    organization_id AS actor_id,
    topic_id,
    fact_type,
    fact_key,
    fact_value,
    collection_state,
    layer,
    source_id,
    source_origin,
    confidence,
    observed_at,
    retrieved_at,
    generated_by,
    request_id,
    created_at,
    semantic_hash,
    creator_class,
    lifecycle_state,
    supersedes_fact_id
   FROM organization_fact;
COMMENT ON VIEW public.actor_fact IS 'Stand-in for organization_fact until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_fact FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_fact TO service_role;
CREATE VIEW public.actor_fact_current WITH (security_invoker=true) AS
 SELECT organization_fact_id AS actor_fact_id,
    organization_id AS actor_id,
    topic_id,
    fact_type,
    fact_key,
    fact_value,
    collection_state,
    layer,
    source_id,
    source_origin,
    confidence,
    observed_at,
    retrieved_at,
    generated_by,
    request_id,
    created_at,
    resolution_state
   FROM organization_fact_current;
COMMENT ON VIEW public.actor_fact_current IS 'Stand-in for organization_fact_current until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_fact_current FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_fact_current TO service_role;
CREATE VIEW public.actor_fact_current_pointer WITH (security_invoker=true) AS
 SELECT organization_id AS actor_id,
    topic_id,
    fact_key,
    organization_fact_id AS actor_fact_id,
    changed_at
   FROM organization_fact_current_pointer;
COMMENT ON VIEW public.actor_fact_current_pointer IS 'Stand-in for organization_fact_current_pointer until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_fact_current_pointer FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_fact_current_pointer TO service_role;
CREATE VIEW public.actor_fact_current_v2 WITH (security_invoker=true) AS
 SELECT organization_fact_id AS actor_fact_id,
    organization_id AS actor_id,
    topic_id,
    fact_type,
    fact_key,
    fact_value,
    collection_state,
    layer,
    source_id,
    source_origin,
    confidence,
    observed_at,
    retrieved_at,
    generated_by,
    request_id,
    created_at,
    semantic_hash,
    creator_class,
    lifecycle_state,
    supersedes_fact_id,
    is_current
   FROM organization_fact_current_v2;
COMMENT ON VIEW public.actor_fact_current_v2 IS 'Stand-in for organization_fact_current_v2 until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_fact_current_v2 FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_fact_current_v2 TO service_role;
CREATE VIEW public.actor_fact_history WITH (security_invoker=true) AS
 SELECT organization_fact_id AS actor_fact_id,
    organization_id AS actor_id,
    topic_id,
    fact_type,
    fact_key,
    fact_value,
    collection_state,
    layer,
    source_id,
    source_origin,
    confidence,
    observed_at,
    retrieved_at,
    generated_by,
    request_id,
    created_at,
    semantic_hash,
    creator_class,
    lifecycle_state,
    supersedes_fact_id,
    is_current
   FROM organization_fact_history;
COMMENT ON VIEW public.actor_fact_history IS 'Stand-in for organization_fact_history until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_fact_history FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_fact_history TO service_role;
CREATE VIEW public.actor_location WITH (security_invoker=true) AS
 SELECT organization_location_id AS actor_location_id,
    organization_id AS actor_id,
    location_name,
    country,
    state_code,
    city,
    region_code,
    latitude,
    longitude,
    is_primary,
    source_id,
    created_at
   FROM organization_location;
COMMENT ON VIEW public.actor_location IS 'Stand-in for organization_location until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_location FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_location TO service_role;
CREATE VIEW public.actor_merge_log WITH (security_invoker=true) AS
 SELECT merge_id,
    winner_organization_id AS winner_actor_id,
    loser_organization_id AS loser_actor_id,
    score,
    method,
    decided_by,
    decided_at,
    pre_merge_state,
    status,
    reverted_at,
    created_at
   FROM organization_merge_log;
COMMENT ON VIEW public.actor_merge_log IS 'Stand-in for organization_merge_log until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_merge_log FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_merge_log TO service_role;
CREATE VIEW public.actor_person WITH (security_invoker=true) AS
 SELECT organization_id AS actor_id,
    person_id,
    role,
    is_current,
    start_date,
    end_date
   FROM organization_person;
COMMENT ON VIEW public.actor_person IS 'Stand-in for organization_person until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_person FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_person TO service_role;
CREATE VIEW public.actor_ranking WITH (security_invoker=true) AS
 SELECT organization_ranking_id AS actor_ranking_id,
    organization_id AS actor_id,
    context_organization_id AS context_actor_id,
    publisher,
    ranking_name,
    ranking_year,
    subject,
    ranked_entity_name,
    position_text,
    source_id,
    created_at
   FROM organization_ranking;
COMMENT ON VIEW public.actor_ranking IS 'Stand-in for organization_ranking until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_ranking FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_ranking TO service_role;
CREATE VIEW public.actor_read WITH (security_invoker=true) AS
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
    funding_summary
   FROM organization_read;
COMMENT ON VIEW public.actor_read IS 'Stand-in for organization_read until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_read FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_read TO service_role;
CREATE VIEW public.actor_relevance WITH (security_invoker=true) AS
 SELECT organization_relevance_id AS actor_relevance_id,
    organization_id AS actor_id,
    challenge_id,
    relevance_score,
    maturity_risk,
    collaboration_orientation,
    why_relevant,
    current_evidence,
    additional_validation_needed,
    source_id,
    created_at,
    challenge_relevance_narrative,
    source_links
   FROM organization_relevance;
COMMENT ON VIEW public.actor_relevance IS 'Stand-in for organization_relevance until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_relevance FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_relevance TO service_role;
CREATE VIEW public.actor_sector WITH (security_invoker=true) AS
 SELECT organization_id AS actor_id,
    sector_id,
    confidence,
    source_id,
    match_strength,
    match_reason,
    is_primary,
    source_origin,
    created_at
   FROM organization_sector;
COMMENT ON VIEW public.actor_sector IS 'Stand-in for organization_sector until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_sector FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_sector TO service_role;
CREATE VIEW public.actor_strategic_connection_check WITH (security_invoker=true) AS
 SELECT connection_check_id,
    organization_id AS actor_id,
    topic_id,
    layer,
    state,
    strategic_entity_id,
    connection_kind,
    source_id,
    fetched_document_ids,
    created_at
   FROM organization_strategic_connection_check;
COMMENT ON VIEW public.actor_strategic_connection_check IS 'Stand-in for organization_strategic_connection_check until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_strategic_connection_check FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_strategic_connection_check TO service_role;
CREATE VIEW public.actor_topic WITH (security_invoker=true) AS
 SELECT organization_id AS actor_id,
    topic_id,
    match_strength,
    match_reason,
    source_id,
    created_at
   FROM organization_topic;
COMMENT ON VIEW public.actor_topic IS 'Stand-in for organization_topic until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_topic FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_topic TO service_role;
CREATE VIEW public.actor_update_subscription WITH (security_invoker=true) AS
 SELECT organization_update_subscription_id AS actor_update_subscription_id,
    organization_ids AS actor_ids,
    sector_codes,
    topic_ids,
    country,
    state_code,
    city,
    region_code,
    start_date,
    end_date,
    cadence,
    requested_by,
    requested_via,
    origin_run_id,
    status,
    last_run_at,
    next_due_at,
    created_at,
    updated_at,
    title,
    focus_terms,
    max_new_organizations_per_run AS max_new_actors_per_run,
    update_options,
    max_usd_per_run,
    discovery_entity,
    discovery_options
   FROM organization_update_subscription;
COMMENT ON VIEW public.actor_update_subscription IS 'Stand-in for organization_update_subscription until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_update_subscription FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_update_subscription TO service_role;
CREATE VIEW public.actor_update_subscription_run WITH (security_invoker=true) AS
 SELECT organization_update_subscription_id AS actor_update_subscription_id,
    collection_run_id,
    dry_run,
    created_at
   FROM organization_update_subscription_run;
COMMENT ON VIEW public.actor_update_subscription_run IS 'Stand-in for organization_update_subscription_run until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_update_subscription_run FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_update_subscription_run TO service_role;
CREATE VIEW public.actor_verification_event WITH (security_invoker=true) AS
 SELECT organization_verification_event_id AS actor_verification_event_id,
    organization_id AS actor_id,
    topic_id,
    decision,
    decided_by,
    decided_at,
    reason,
    rejection_reason,
    source_id,
    decision_origin,
    migration_batch_id,
    recorded_at
   FROM organization_verification_event;
COMMENT ON VIEW public.actor_verification_event IS 'Stand-in for organization_verification_event until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_verification_event FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_verification_event TO service_role;
CREATE VIEW public.hub_actor WITH (security_invoker=true) AS
 SELECT hub_id,
    organization_id AS actor_id,
    relationship_type,
    is_primary,
    created_at,
    topic_id,
    distance_miles,
    assignment_outcome,
    outside_radius,
    overlap_flag,
    source_id
   FROM hub_organization;
COMMENT ON VIEW public.hub_actor IS 'Stand-in for hub_organization until the code uses the new name (migration 720).';
REVOKE ALL ON public.hub_actor FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.hub_actor TO service_role;
CREATE VIEW public.hub_actor_removed WITH (security_invoker=true) AS
 SELECT hub_id,
    organization_id AS actor_id,
    membership,
    reason,
    decided_by,
    removed_at
   FROM hub_organization_removed;
COMMENT ON VIEW public.hub_actor_removed IS 'Stand-in for hub_organization_removed until the code uses the new name (migration 720).';
REVOKE ALL ON public.hub_actor_removed FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.hub_actor_removed TO service_role;

DELETE FROM compass.migration_snapshot WHERE migration_id = '800';
NOTIFY pgrst, 'reload schema';

COMMIT;
