-- Rollback 720: the actor names come back exactly as they were.
-- Run in the SQL editor, then: DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '720';
-- The data is untouched; only names, the stand-in views, the rewritten functions and
-- the category label change back.

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM compass.migration_snapshot WHERE migration_id = '720') THEN
        RAISE EXCEPTION 'rollback 720 refused: no snapshot of 720 (it was not applied here)';
    END IF;
END $guard$;

-- The stand-in views go first: the old names are needed again.
DROP VIEW public.actor_read;
DROP VIEW public.actor_fact_history;
DROP VIEW public.actor_fact_current_v2;
DROP VIEW public.actor_fact_current;
DROP VIEW public.actor_descendants;
DROP VIEW public.actor_descendant_edge;
DROP VIEW public.hub_actor_removed;
DROP VIEW public.hub_actor;
DROP VIEW public.actor_verification_event;
DROP VIEW public.actor_update_subscription_run;
DROP VIEW public.actor_update_subscription;
DROP VIEW public.actor_topic;
DROP VIEW public.actor_strategic_connection_check;
DROP VIEW public.actor_sector;
DROP VIEW public.actor_relevance;
DROP VIEW public.actor_ranking;
DROP VIEW public.actor_person;
DROP VIEW public.actor_merge_log;
DROP VIEW public.actor_location;
DROP VIEW public.actor_fact_current_pointer;
DROP VIEW public.actor_fact;
DROP VIEW public.actor_evaluation;
DROP VIEW public.actor_details;
DROP VIEW public.actor_category_type_definition;
DROP VIEW public.actor_category_migration_audit;
DROP VIEW public.actor_category_definition;
DROP VIEW public.actor;

UPDATE public.organization_category_definition
   SET display_name = replace(display_name, 'Corporate Organization', 'Corporate Actor')
 WHERE display_name LIKE '%Corporate Organization%';

-- Functions: names back, then the saved definitions (byte for byte).
DROP FUNCTION public.ghus_organization_details_refresh(uuid, text);
ALTER FUNCTION public.ghus_organization_details_on_pointer() RENAME TO ghus_actor_details_on_pointer;
ALTER FUNCTION public.ghus_organization_details_on_topicless_fact() RENAME TO ghus_actor_details_on_topicless_fact;
ALTER FUNCTION public.ghus_guard_organization_status() RENAME TO ghus_guard_actor_status;
ALTER FUNCTION public.ghus_prevent_organization_family_cycle() RENAME TO ghus_prevent_actor_family_cycle;
ALTER FUNCTION public.ghus_project_organization_verification_status() RENAME TO ghus_project_actor_verification_status;
DO $restore$
DECLARE d record;
BEGIN
    FOR d IN SELECT definition FROM compass.migration_snapshot
              WHERE migration_id = '720' AND object_name NOT LIKE 'rename:%' LOOP
        EXECUTE d.definition;
    END LOOP;
END $restore$;

-- Constraint, index, trigger and policy names, exactly as recorded.
DO $names$
DECLARE x record; parts text[];
BEGIN
    FOR x IN SELECT object_name, definition FROM compass.migration_snapshot
              WHERE migration_id = '720'
                AND split_part(object_name, ':', 2) IN ('constraint', 'index', 'trigger', 'policy') LOOP
        parts := string_to_array(x.object_name, ':');
        CASE parts[2]
            WHEN 'constraint' THEN EXECUTE format('ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I', parts[3], x.definition, parts[4]);
            WHEN 'index' THEN EXECUTE format('ALTER INDEX public.%I RENAME TO %I', x.definition, parts[4]);
            WHEN 'trigger' THEN EXECUTE format('ALTER TRIGGER %I ON public.%I RENAME TO %I', x.definition, parts[3], parts[4]);
            WHEN 'policy' THEN EXECUTE format('ALTER POLICY %I ON public.%I RENAME TO %I', x.definition, parts[3], parts[4]);
        END CASE;
    END LOOP;
END $names$;

-- Columns, then tables and views.
ALTER TABLE public.organization RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization RENAME COLUMN merged_into_organization_id TO merged_into_actor_id;
ALTER TABLE public.organization RENAME COLUMN organization_category TO actor_category;
ALTER TABLE public.organization_category_migration_audit RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_details RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_details RENAME COLUMN organization_category_type TO actor_category_type;
ALTER TABLE public.organization_details RENAME COLUMN organization_relationships TO actor_relationships;
ALTER TABLE public.organization_evaluation RENAME COLUMN organization_evaluation_id TO actor_evaluation_id;
ALTER TABLE public.organization_evaluation RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_fact RENAME COLUMN organization_fact_id TO actor_fact_id;
ALTER TABLE public.organization_fact RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_fact_current_pointer RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_fact_current_pointer RENAME COLUMN organization_fact_id TO actor_fact_id;
ALTER TABLE public.organization_location RENAME COLUMN organization_location_id TO actor_location_id;
ALTER TABLE public.organization_location RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_merge_log RENAME COLUMN winner_organization_id TO winner_actor_id;
ALTER TABLE public.organization_merge_log RENAME COLUMN loser_organization_id TO loser_actor_id;
ALTER TABLE public.organization_person RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_ranking RENAME COLUMN organization_ranking_id TO actor_ranking_id;
ALTER TABLE public.organization_ranking RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_ranking RENAME COLUMN context_organization_id TO context_actor_id;
ALTER TABLE public.organization_relevance RENAME COLUMN organization_relevance_id TO actor_relevance_id;
ALTER TABLE public.organization_relevance RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_sector RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_strategic_connection_check RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_topic RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_update_subscription RENAME COLUMN organization_update_subscription_id TO actor_update_subscription_id;
ALTER TABLE public.organization_update_subscription RENAME COLUMN organization_ids TO actor_ids;
ALTER TABLE public.organization_update_subscription RENAME COLUMN max_new_organizations_per_run TO max_new_actors_per_run;
ALTER TABLE public.organization_update_subscription_run RENAME COLUMN organization_update_subscription_id TO actor_update_subscription_id;
ALTER TABLE public.organization_verification_event RENAME COLUMN organization_verification_event_id TO actor_verification_event_id;
ALTER TABLE public.organization_verification_event RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.hub_organization RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.hub_organization_removed RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_descendant_edge RENAME COLUMN root_organization_id TO root_actor_id;
ALTER TABLE public.organization_descendant_edge RENAME COLUMN descendant_organization_id TO descendant_actor_id;
ALTER TABLE public.organization_descendants RENAME COLUMN root_organization_id TO root_actor_id;
ALTER TABLE public.organization_descendants RENAME COLUMN descendant_organization_id TO descendant_actor_id;
ALTER TABLE public.organization_fact_current RENAME COLUMN organization_fact_id TO actor_fact_id;
ALTER TABLE public.organization_fact_current RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_fact_current_v2 RENAME COLUMN organization_fact_id TO actor_fact_id;
ALTER TABLE public.organization_fact_current_v2 RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_fact_history RENAME COLUMN organization_fact_id TO actor_fact_id;
ALTER TABLE public.organization_fact_history RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_read RENAME COLUMN organization_id TO actor_id;
ALTER TABLE public.organization_read RENAME COLUMN organization_category TO actor_category;
ALTER TABLE public.organization_read RENAME COLUMN merged_into_organization_id TO merged_into_actor_id;
ALTER VIEW public.organization_descendant_edge RENAME TO actor_descendant_edge;
ALTER VIEW public.organization_descendants RENAME TO actor_descendants;
ALTER VIEW public.organization_fact_current RENAME TO actor_fact_current;
ALTER VIEW public.organization_fact_current_v2 RENAME TO actor_fact_current_v2;
ALTER VIEW public.organization_fact_history RENAME TO actor_fact_history;
ALTER VIEW public.organization_read RENAME TO actor_read;
ALTER TABLE public.organization RENAME TO actor;
ALTER TABLE public.organization_category_definition RENAME TO actor_category_definition;
ALTER TABLE public.organization_category_migration_audit RENAME TO actor_category_migration_audit;
ALTER TABLE public.organization_category_type_definition RENAME TO actor_category_type_definition;
ALTER TABLE public.organization_details RENAME TO actor_details;
ALTER TABLE public.organization_evaluation RENAME TO actor_evaluation;
ALTER TABLE public.organization_fact RENAME TO actor_fact;
ALTER TABLE public.organization_fact_current_pointer RENAME TO actor_fact_current_pointer;
ALTER TABLE public.organization_location RENAME TO actor_location;
ALTER TABLE public.organization_merge_log RENAME TO actor_merge_log;
ALTER TABLE public.organization_person RENAME TO actor_person;
ALTER TABLE public.organization_ranking RENAME TO actor_ranking;
ALTER TABLE public.organization_relevance RENAME TO actor_relevance;
ALTER TABLE public.organization_sector RENAME TO actor_sector;
ALTER TABLE public.organization_strategic_connection_check RENAME TO actor_strategic_connection_check;
ALTER TABLE public.organization_topic RENAME TO actor_topic;
ALTER TABLE public.organization_update_subscription RENAME TO actor_update_subscription;
ALTER TABLE public.organization_update_subscription_run RENAME TO actor_update_subscription_run;
ALTER TABLE public.organization_verification_event RENAME TO actor_verification_event;
ALTER TABLE public.hub_organization RENAME TO hub_actor;
ALTER TABLE public.hub_organization_removed RENAME TO hub_actor_removed;

DELETE FROM compass.migration_snapshot WHERE migration_id = '720';

COMMIT;
