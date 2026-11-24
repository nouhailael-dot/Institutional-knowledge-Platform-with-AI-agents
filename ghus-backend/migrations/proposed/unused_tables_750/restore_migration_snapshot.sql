-- The rows of compass.migration_snapshot as they were on Supabase on 24 Nov 2026 (256 rows:
-- the definitions migrations 710 and 720 saved for their rollbacks). Migration 750 removes the
-- table; this file brings it back, so 710 and 720 can still be rolled back. Safe to run twice.

BEGIN;

CREATE TABLE IF NOT EXISTS compass.migration_snapshot (
    migration_id text NOT NULL,
    object_name text NOT NULL,
    definition text NOT NULL,
    taken_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT migration_snapshot_pkey PRIMARY KEY (migration_id, object_name)
);
ALTER TABLE compass.migration_snapshot ENABLE ROW LEVEL SECURITY;

INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('710', 'public.actor_read', 'CREATE OR REPLACE VIEW public.actor_read AS  SELECT a.actor_id,
    a.name,
    a.slug,
    a.actor_category,
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
    a.merged_into_actor_id,
    a.alt_names,
    a.created_at,
    a.updated_at,
    f.primary_technical_focus,
    f.technical_approach,
    f.current_activities,
    f.technology_ip_notes,
    f.key_constraints,
    f.funding_summary,
    (f.estimated_trl)::smallint AS estimated_trl,
    f.primary_lifecycle_role
   FROM (actor a
     LEFT JOIN LATERAL ( SELECT max((actor_fact.fact_value #>> ''{}''::text[])) FILTER (WHERE (actor_fact.fact_key = ''primary_technical_focus''::text)) AS primary_technical_focus,
            max((actor_fact.fact_value #>> ''{}''::text[])) FILTER (WHERE (actor_fact.fact_key = ''technical_approach''::text)) AS technical_approach,
            max((actor_fact.fact_value #>> ''{}''::text[])) FILTER (WHERE (actor_fact.fact_key = ''current_activities''::text)) AS current_activities,
            max((actor_fact.fact_value #>> ''{}''::text[])) FILTER (WHERE (actor_fact.fact_key = ''technology_ip_notes''::text)) AS technology_ip_notes,
            max((actor_fact.fact_value #>> ''{}''::text[])) FILTER (WHERE (actor_fact.fact_key = ''key_constraints''::text)) AS key_constraints,
            max((actor_fact.fact_value #>> ''{}''::text[])) FILTER (WHERE (actor_fact.fact_key = ''funding_summary''::text)) AS funding_summary,
            max((actor_fact.fact_value #>> ''{}''::text[])) FILTER (WHERE (actor_fact.fact_key = ''estimated_trl''::text)) AS estimated_trl,
            max((actor_fact.fact_value #>> ''{}''::text[])) FILTER (WHERE (actor_fact.fact_key = ''primary_lifecycle_role''::text)) AS primary_lifecycle_role
           FROM actor_fact
          WHERE ((actor_fact.actor_id = a.actor_id) AND (actor_fact.fact_type = ''legacy_baseline''::text))) f ON (true))
  WHERE (a.status IS DISTINCT FROM ''rejected''::text);', '2026-11-19T20:29:19.011430+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('710', 'public.ghus_guard_no_delete()', 'CREATE OR REPLACE FUNCTION public.ghus_guard_no_delete()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION
        ''% is never deleted: reject the record and keep it, with its reason'',
        TG_TABLE_NAME;
END $function$
', '2026-11-19T20:29:19.011430+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('710', 'public.ghus_guard_sector_link_append_only()', 'CREATE OR REPLACE FUNCTION public.ghus_guard_sector_link_append_only()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION ''% is append-only: % is not permitted'', TG_TABLE_NAME, TG_OP;
END $function$
', '2026-11-19T20:29:19.011430+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('710', 'public.ghus_guard_subscription_run_append_only()', 'CREATE OR REPLACE FUNCTION public.ghus_guard_subscription_run_append_only()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION ''actor_update_subscription_run is append-only: % is not permitted'', TG_OP;
END $function$
', '2026-11-19T20:29:19.011430+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('710', 'public.ghus_reject_mutation()', 'CREATE OR REPLACE FUNCTION public.ghus_reject_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION ''% is append-only'', TG_TABLE_NAME;
END;
$function$
', '2026-11-19T20:29:19.011430+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'public.ghus_actor_details_on_pointer()', 'CREATE OR REPLACE FUNCTION public.ghus_actor_details_on_pointer()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    PERFORM ghus_actor_details_refresh(NEW.actor_id, NEW.fact_key);
    RETURN NULL;
END $function$
', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'public.ghus_actor_details_on_topicless_fact()', 'CREATE OR REPLACE FUNCTION public.ghus_actor_details_on_topicless_fact()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    PERFORM ghus_actor_details_refresh(NEW.actor_id, NEW.fact_key);
    RETURN NULL;
END $function$
', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'public.ghus_actor_details_refresh(p_actor uuid, p_key text)', 'CREATE OR REPLACE FUNCTION public.ghus_actor_details_refresh(p_actor uuid, p_key text)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_value jsonb;
    v_source jsonb;
    v_column boolean;
BEGIN
    SELECT CASE WHEN f.collection_state = ''found'' THEN f.fact_value
                ELSE to_jsonb(f.collection_state) END,
           jsonb_strip_nulls(jsonb_build_object(
               ''source_url'', s.url, ''retrieved_at'', f.retrieved_at,
               ''confidence'', f.confidence, ''topic_id'', f.topic_id,
               ''actor_fact_id'', f.actor_fact_id))
      INTO v_value, v_source
      FROM actor_fact f
      LEFT JOIN source s ON s.source_id = f.source_id
     WHERE f.actor_id = p_actor AND f.fact_key = p_key
       AND (EXISTS (SELECT 1 FROM actor_fact_current_pointer p
                     WHERE p.actor_fact_id = f.actor_fact_id)
            OR (f.topic_id IS NULL AND EXISTS (
                    SELECT 1 FROM actor_fact_current c
                     WHERE c.actor_fact_id = f.actor_fact_id
                       AND c.resolution_state = ''accepted'')))
     ORDER BY (f.collection_state = ''found'') DESC, f.retrieved_at DESC NULLS LAST,
              f.created_at DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO actor_details (actor_id) VALUES (p_actor) ON CONFLICT (actor_id) DO NOTHING;

    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = ''public'' AND table_name = ''actor_details''
                      AND column_name = p_key
                      AND column_name NOT IN (''actor_id'', ''other_facts'', ''fact_sources'',
                                              ''updated_at''))
      INTO v_column;

    IF v_column THEN
        EXECUTE format(
            ''UPDATE actor_details SET %I = $1, fact_sources = fact_sources || $2, ''
            ''updated_at = now() WHERE actor_id = $3'', p_key)
        USING v_value, jsonb_build_object(p_key, v_source), p_actor;
    ELSE
        UPDATE actor_details
           SET other_facts = other_facts || jsonb_build_object(p_key, v_value),
               fact_sources = fact_sources || jsonb_build_object(p_key, v_source),
               updated_at = now()
         WHERE actor_id = p_actor;
    END IF;
END $function$
', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'public.ghus_guard_actor_status()', 'CREATE OR REPLACE FUNCTION public.ghus_guard_actor_status()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.status IN (''verified'',''rejected'')
     AND COALESCE(current_setting(''ghus.verification_projection'',true),''off'') <> ''on''
  THEN
    RAISE EXCEPTION ''verified/rejected status requires actor_verification_event'';
  END IF;
  RETURN NEW;
END;
$function$
', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'public.ghus_guard_ranking_is_university()', 'CREATE OR REPLACE FUNCTION public.ghus_guard_ranking_is_university()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE category text;
BEGIN
    SELECT a.actor_category INTO category FROM actor a WHERE a.actor_id = NEW.actor_id;
    IF category IS DISTINCT FROM ''university_academic'' THEN
        RAISE EXCEPTION
            ''rankings are recorded for university actors only; actor % is %'',
            NEW.actor_id, COALESCE(category, ''unclassified'');
    END IF;
    RETURN NEW;
END $function$
', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'public.ghus_guard_subscription_run_append_only()', 'CREATE OR REPLACE FUNCTION public.ghus_guard_subscription_run_append_only()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = ''DELETE'' AND compass.purge_door_open() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION ''actor_update_subscription_run is append-only: % is not permitted'', TG_OP;
END $function$
', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'public.ghus_prevent_actor_family_cycle()', 'CREATE OR REPLACE FUNCTION public.ghus_prevent_actor_family_cycle()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE cycle_found boolean;
BEGIN
    IF NEW.relationship_type NOT IN (''unit_of'',''operated_by'') THEN
        RETURN NEW;
    END IF;
    WITH RECURSIVE ancestors(actor_id,path) AS (
        SELECT NEW.object_id,ARRAY[NEW.object_id]
        UNION ALL
        SELECT edge.object_id,ancestors.path || edge.object_id
        FROM ancestors
        JOIN entity_edge edge
          ON edge.subject_type=''actor'' AND edge.object_type=''actor''
         AND edge.subject_id=ancestors.actor_id
         AND edge.relationship_type IN (''unit_of'',''operated_by'')
        WHERE NOT edge.object_id=ANY(ancestors.path)
    )
    SELECT EXISTS(SELECT 1 FROM ancestors WHERE actor_id=NEW.subject_id)
    INTO cycle_found;
    IF cycle_found THEN
        RAISE EXCEPTION ''actor family cycle refused for % -> %'',NEW.subject_id,NEW.object_id;
    END IF;
    RETURN NEW;
END $function$
', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'public.ghus_project_actor_verification_status()', 'CREATE OR REPLACE FUNCTION public.ghus_project_actor_verification_status()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''public''
AS $function$
BEGIN
    PERFORM set_config(''ghus.verification_projection'',''on'',true);
    UPDATE actor SET status=NEW.decision,updated_at=now() WHERE actor_id=NEW.actor_id;
    PERFORM set_config(''ghus.verification_projection'',''off'',true);
    RETURN NEW;
END;
$function$
', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'public.ghus_validate_entity_edge()', 'CREATE OR REPLACE FUNCTION public.ghus_validate_entity_edge()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    allowed_subjects text[];
    allowed_objects text[];
    endpoint_exists boolean;
BEGIN
    SELECT subject_types,object_types INTO allowed_subjects,allowed_objects
    FROM entity_edge_type_definition
    WHERE relationship_type=NEW.relationship_type;
    IF allowed_subjects IS NULL
       OR NOT NEW.subject_type=ANY(allowed_subjects)
       OR NOT NEW.object_type=ANY(allowed_objects) THEN
        RAISE EXCEPTION ''invalid endpoint pair % -> % for %'',
            NEW.subject_type,NEW.object_type,NEW.relationship_type;
    END IF;

    IF NEW.subject_type=''actor'' THEN
        SELECT EXISTS(SELECT 1 FROM actor WHERE actor_id=NEW.subject_id) INTO endpoint_exists;
    ELSIF NEW.subject_type=''person'' THEN
        SELECT EXISTS(SELECT 1 FROM person WHERE person_id=NEW.subject_id) INTO endpoint_exists;
    ELSIF NEW.subject_type=''event'' THEN
        SELECT EXISTS(SELECT 1 FROM event WHERE event_id=NEW.subject_id) INTO endpoint_exists;
    ELSE
        SELECT EXISTS(SELECT 1 FROM strategic_entity WHERE strategic_entity_id=NEW.subject_id) INTO endpoint_exists;
    END IF;
    IF NOT endpoint_exists THEN
        RAISE EXCEPTION ''missing % subject endpoint %'',NEW.subject_type,NEW.subject_id;
    END IF;

    IF NEW.object_type=''actor'' THEN
        SELECT EXISTS(SELECT 1 FROM actor WHERE actor_id=NEW.object_id) INTO endpoint_exists;
    ELSIF NEW.object_type=''person'' THEN
        SELECT EXISTS(SELECT 1 FROM person WHERE person_id=NEW.object_id) INTO endpoint_exists;
    ELSIF NEW.object_type=''event'' THEN
        SELECT EXISTS(SELECT 1 FROM event WHERE event_id=NEW.object_id) INTO endpoint_exists;
    ELSE
        SELECT EXISTS(SELECT 1 FROM strategic_entity WHERE strategic_entity_id=NEW.object_id) INTO endpoint_exists;
    END IF;
    IF NOT endpoint_exists THEN
        RAISE EXCEPTION ''missing % object endpoint %'',NEW.object_type,NEW.object_id;
    END IF;
    RETURN NEW;
END $function$
', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:hub_organization_removed:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:hub_organization:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_category_migration_audit:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_descendant_edge:descendant_actor_id', 'descendant_organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_descendant_edge:root_actor_id', 'root_organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_descendants:descendant_actor_id', 'descendant_organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_descendants:root_actor_id', 'root_organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_details:actor_category_type', 'organization_category_type', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_details:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_details:actor_relationships', 'organization_relationships', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_evaluation:actor_evaluation_id', 'organization_evaluation_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_evaluation:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact_current_pointer:actor_fact_id', 'organization_fact_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact_current_pointer:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact_current_v2:actor_fact_id', 'organization_fact_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact_current_v2:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact_current:actor_fact_id', 'organization_fact_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact_current:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact_history:actor_fact_id', 'organization_fact_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact_history:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact:actor_fact_id', 'organization_fact_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_fact:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_location:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_location:actor_location_id', 'organization_location_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_merge_log:loser_actor_id', 'loser_organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_merge_log:winner_actor_id', 'winner_organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_person:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_ranking:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_ranking:actor_ranking_id', 'organization_ranking_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_ranking:context_actor_id', 'context_organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_read:actor_category', 'organization_category', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_read:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_read:merged_into_actor_id', 'merged_into_organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_relevance:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_relevance:actor_relevance_id', 'organization_relevance_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_sector:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_strategic_connection_check:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_topic:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_update_subscription_run:actor_update_subscription_id', 'organization_update_subscription_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_update_subscription:actor_ids', 'organization_ids', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_update_subscription:actor_update_subscription_id', 'organization_update_subscription_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_update_subscription:max_new_actors_per_run', 'max_new_organizations_per_run', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_verification_event:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization_verification_event:actor_verification_event_id', 'organization_verification_event_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization:actor_category', 'organization_category', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization:actor_id', 'organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:column:organization:merged_into_actor_id', 'merged_into_organization_id', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:hub_organization_removed:hub_actor_removed_pkey', 'hub_organization_removed_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:hub_organization:ck_hub_actor_assignment_outcome', 'ck_hub_organization_assignment_outcome', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:hub_organization:ck_hub_actor_radius_known', 'ck_hub_organization_radius_known', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:hub_organization:ck_hub_actor_source_or_legacy', 'ck_hub_organization_source_or_legacy', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:hub_organization:fk_hub_actor_hub_topic', 'fk_hub_organization_hub_topic', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:hub_organization:hub_actor_actor_id_fkey', 'hub_organization_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:hub_organization:hub_actor_hub_id_fkey', 'hub_organization_hub_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:hub_organization:hub_actor_pkey', 'hub_organization_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_definition:actor_category_definition_display_name_key', 'organization_category_definition_display_name_key', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_definition:actor_category_definition_pkey', 'organization_category_definition_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_definition:actor_category_definition_sort_order_check', 'organization_category_definition_sort_order_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_definition:actor_category_definition_sort_order_key', 'organization_category_definition_sort_order_key', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_migration_audit:actor_category_migration_audit_actor_id_fkey', 'organization_category_migration_audit_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_migration_audit:actor_category_migration_audit_mapped_category_fkey', 'organization_category_migration_audit_mapped_category_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_migration_audit:actor_category_migration_audit_mapping_status_check', 'organization_category_migration_audit_mapping_status_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_migration_audit:actor_category_migration_audit_pkey', 'organization_category_migration_audit_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_type_definition:actor_category_type_definition_category_code_fkey', 'organization_category_type_definition_category_code_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_type_definition:actor_category_type_definition_pkey', 'organization_category_type_definition_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_category_type_definition:ck_actor_category_type_other_flag', 'ck_organization_category_type_other_flag', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_details:actor_details_actor_id_fkey', 'organization_details_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_details:actor_details_pkey', 'organization_details_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_evaluation:actor_evaluation_actor_id_fkey', 'organization_evaluation_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_evaluation:actor_evaluation_pkey', 'organization_evaluation_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_evaluation:actor_evaluation_source_id_fkey', 'organization_evaluation_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_evaluation:uq_actor_evaluation_context', 'uq_organization_evaluation_context', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact_current_pointer:actor_fact_current_pointer_actor_fact_id_fkey', 'organization_fact_current_pointer_organization_fact_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact_current_pointer:actor_fact_current_pointer_actor_fact_id_key', 'organization_fact_current_pointer_organization_fact_id_key', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact_current_pointer:actor_fact_current_pointer_actor_id_fkey', 'organization_fact_current_pointer_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact_current_pointer:actor_fact_current_pointer_pkey', 'organization_fact_current_pointer_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact_current_pointer:actor_fact_current_pointer_topic_id_fkey', 'organization_fact_current_pointer_topic_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_actor_id_fkey', 'organization_fact_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_check', 'organization_fact_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_collection_state_check', 'organization_fact_collection_state_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_confidence_check', 'organization_fact_confidence_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_layer_check', 'organization_fact_layer_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_pkey', 'organization_fact_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_source_id_fkey', 'organization_fact_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_source_origin_fkey', 'organization_fact_source_origin_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_supersedes_fact_id_fkey', 'organization_fact_supersedes_fact_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:actor_fact_topic_id_fkey', 'organization_fact_topic_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:ck_actor_fact_creator_class', 'ck_organization_fact_creator_class', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_fact:ck_actor_fact_lifecycle_state', 'ck_organization_fact_lifecycle_state', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_location:actor_location_actor_id_fkey', 'organization_location_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_location:actor_location_check', 'organization_location_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_location:actor_location_pkey', 'organization_location_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_location:actor_location_region_code_fkey', 'organization_location_region_code_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_location:actor_location_source_id_fkey', 'organization_location_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_location:actor_location_state_code_fkey', 'organization_location_state_code_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_merge_log:actor_merge_log_loser_actor_id_fkey', 'organization_merge_log_loser_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_merge_log:actor_merge_log_pkey', 'organization_merge_log_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_merge_log:actor_merge_log_winner_actor_id_fkey', 'organization_merge_log_winner_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_person:actor_person_actor_id_fkey', 'organization_person_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_person:actor_person_person_id_fkey', 'organization_person_person_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_person:actor_person_pkey', 'organization_person_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_ranking:actor_ranking_actor_id_fkey', 'organization_ranking_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_ranking:actor_ranking_context_actor_id_fkey', 'organization_ranking_context_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_ranking:actor_ranking_pkey', 'organization_ranking_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_ranking:actor_ranking_publisher_check', 'organization_ranking_publisher_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_ranking:actor_ranking_ranking_year_check', 'organization_ranking_ranking_year_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_ranking:actor_ranking_source_id_fkey', 'organization_ranking_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_relevance:actor_relevance_actor_id_fkey', 'organization_relevance_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_relevance:actor_relevance_challenge_id_fkey', 'organization_relevance_challenge_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_relevance:actor_relevance_pkey', 'organization_relevance_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_relevance:actor_relevance_source_id_fkey', 'organization_relevance_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_relevance:uq_actor_challenge', 'uq_organization_challenge', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_sector:actor_sector_actor_id_fkey', 'organization_sector_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_sector:actor_sector_pkey', 'organization_sector_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_sector:actor_sector_sector_id_fkey', 'organization_sector_sector_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_sector:actor_sector_source_id_fkey', 'organization_sector_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_sector:actor_sector_source_origin_fkey', 'organization_sector_source_origin_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_sector:ck_actor_sector_reason', 'ck_organization_sector_reason', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_sector:ck_actor_sector_strength', 'ck_organization_sector_strength', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_strategic_connection_check:actor_strategic_connection_check_actor_id_fkey', 'organization_strategic_connection_check_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_strategic_connection_check:actor_strategic_connection_check_check', 'organization_strategic_connection_check_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_strategic_connection_check:actor_strategic_connection_check_layer_check', 'organization_strategic_connection_check_layer_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_strategic_connection_check:actor_strategic_connection_check_pkey', 'organization_strategic_connection_check_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_strategic_connection_check:actor_strategic_connection_check_source_id_fkey', 'organization_strategic_connection_check_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_strategic_connection_check:actor_strategic_connection_check_state_check', 'organization_strategic_connection_check_state_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_strategic_connection_check:actor_strategic_connection_check_topic_id_fkey', 'organization_strategic_connection_check_topic_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_topic:actor_topic_actor_id_fkey', 'organization_topic_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_topic:actor_topic_match_reason_check', 'organization_topic_match_reason_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_topic:actor_topic_match_strength_check', 'organization_topic_match_strength_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_topic:actor_topic_pkey', 'organization_topic_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_topic:actor_topic_source_id_fkey', 'organization_topic_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_topic:actor_topic_topic_id_fkey', 'organization_topic_topic_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription_run:actor_update_subscription_run_collection_run_id_fkey', 'organization_update_subscription_run_collection_run_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription_run:actor_update_subscription_run_pkey', 'organization_update_subscription_run_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:actor_update_subscription_origin_run_id_fkey', 'organization_update_subscription_origin_run_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:actor_update_subscription_pkey', 'organization_update_subscription_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:actor_update_subscription_region_code_fkey', 'organization_update_subscription_region_code_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:actor_update_subscription_state_code_fkey', 'organization_update_subscription_state_code_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_cadence', 'ck_organization_update_subscription_cadence', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_cap', 'ck_organization_update_subscription_cap', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_discovery_options', 'ck_organization_update_subscription_discovery_options', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_discovery_topic', 'ck_organization_update_subscription_discovery_topic', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_entity', 'ck_organization_update_subscription_entity', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_entity_via', 'ck_organization_update_subscription_entity_via', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_focus_terms', 'ck_organization_update_subscription_focus_terms', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_max_usd', 'ck_organization_update_subscription_max_usd', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_options', 'ck_organization_update_subscription_options', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_period', 'ck_organization_update_subscription_period', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_scope', 'ck_organization_update_subscription_scope', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_status', 'ck_organization_update_subscription_status', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_title', 'ck_organization_update_subscription_title', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_update_request', 'ck_organization_update_subscription_update_request', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_update_subscription:ck_actor_update_subscription_via', 'ck_organization_update_subscription_via', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_verification_event:actor_verification_event_actor_id_fkey', 'organization_verification_event_organization_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_verification_event:actor_verification_event_check', 'organization_verification_event_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_verification_event:actor_verification_event_decision_check', 'organization_verification_event_decision_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_verification_event:actor_verification_event_pkey', 'organization_verification_event_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_verification_event:actor_verification_event_source_id_fkey', 'organization_verification_event_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_verification_event:actor_verification_event_topic_id_fkey', 'organization_verification_event_topic_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization_verification_event:ck_actor_verification_event_origin', 'ck_organization_verification_event_origin', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization:actor_pkey', 'organization_pkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization:actor_slug_key', 'organization_slug_key', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization:actor_source_id_fkey', 'organization_source_id_fkey', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization:ck_actor_category_complete', 'ck_organization_category_complete', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization:ck_actor_other_type_note', 'ck_organization_other_type_note', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization:ck_actor_status_v2', 'ck_organization_status_v2', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization:fk_actor_category_type', 'fk_organization_category_type', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:constraint:organization:fk_actor_merged_into_actor', 'fk_organization_merged_into_organization', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:function_recreated::ghus_actor_details_refresh', 'ghus_organization_details_refresh', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:function::ghus_actor_details_on_pointer', 'ghus_organization_details_on_pointer', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:function::ghus_actor_details_on_topicless_fact', 'ghus_organization_details_on_topicless_fact', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:function::ghus_guard_actor_status', 'ghus_guard_organization_status', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:function::ghus_prevent_actor_family_cycle', 'ghus_prevent_organization_family_cycle', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:function::ghus_project_actor_verification_status', 'ghus_project_organization_verification_status', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:hub_organization:ix_hub_actor_topic', 'ix_hub_organization_topic', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_category_type_definition:ux_actor_category_one_other', 'ux_organization_category_one_other', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_evaluation:ix_actor_evaluation_actor', 'ix_organization_evaluation_organization', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_evaluation:ix_actor_evaluation_context', 'ix_organization_evaluation_context', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_fact:ix_actor_fact_lookup', 'ix_organization_fact_lookup', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_fact:ix_actor_fact_semantic', 'ix_organization_fact_semantic', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_location:uq_actor_one_primary_location', 'uq_organization_one_primary_location', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_merge_log:ix_actor_merge_log_loser', 'ix_organization_merge_log_loser', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_merge_log:ix_actor_merge_log_winner', 'ix_organization_merge_log_winner', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_sector:ix_actor_sector_sector', 'ix_organization_sector_sector', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_sector:ux_actor_sector_primary', 'ux_organization_sector_primary', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_topic:ix_actor_topic_topic', 'ix_organization_topic_topic', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_update_subscription_run:ix_actor_update_subscription_run_run', 'ix_organization_update_subscription_run_run', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_update_subscription:ix_actor_update_subscription_due', 'ix_organization_update_subscription_due', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_update_subscription:ix_actor_update_subscription_status', 'ix_organization_update_subscription_status', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_verification_event:ix_actor_verification_event_latest', 'ix_organization_verification_event_latest', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization_verification_event:ux_actor_existing_canonical_bootstrap', 'ux_organization_existing_canonical_bootstrap', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization:ix_actor_alternate_names_gin', 'ix_organization_alternate_names_gin', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization:ix_actor_geography', 'ix_organization_geography', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization:ix_actor_name_normalized', 'ix_organization_name_normalized', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:index:organization:ix_actor_website_domain', 'ix_organization_website_domain', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:policy:organization_verification_event:actor_verification_event_ghus_insert', 'organization_verification_event_ghus_insert', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:policy:organization_verification_event:actor_verification_event_read', 'organization_verification_event_read', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor', 'organization', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_category_definition', 'organization_category_definition', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_category_migration_audit', 'organization_category_migration_audit', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_category_type_definition', 'organization_category_type_definition', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_descendant_edge', 'organization_descendant_edge', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_descendants', 'organization_descendants', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_details', 'organization_details', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_evaluation', 'organization_evaluation', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_fact', 'organization_fact', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_fact_current', 'organization_fact_current', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_fact_current_pointer', 'organization_fact_current_pointer', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_fact_current_v2', 'organization_fact_current_v2', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_fact_history', 'organization_fact_history', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_location', 'organization_location', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_merge_log', 'organization_merge_log', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_person', 'organization_person', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_ranking', 'organization_ranking', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_read', 'organization_read', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_relevance', 'organization_relevance', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_sector', 'organization_sector', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_strategic_connection_check', 'organization_strategic_connection_check', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_topic', 'organization_topic', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_update_subscription', 'organization_update_subscription', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_update_subscription_run', 'organization_update_subscription_run', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::actor_verification_event', 'organization_verification_event', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::hub_actor', 'hub_organization', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:relation::hub_actor_removed', 'hub_organization_removed', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:hub_organization_removed:hub_actor_removed_append_only', 'hub_organization_removed_append_only', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:hub_organization:hub_actor_no_delete', 'hub_organization_no_delete', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_category_migration_audit:actor_category_migration_audit_append_only', 'organization_category_migration_audit_append_only', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_fact_current_pointer:actor_details_follows_pointer', 'organization_details_follows_pointer', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_fact:actor_details_follows_topicless_fact', 'organization_details_follows_topicless_fact', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_fact:actor_fact_append_only', 'organization_fact_append_only', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_location:actor_location_no_delete', 'organization_location_no_delete', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_ranking:actor_ranking_append_only', 'organization_ranking_append_only', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_ranking:actor_ranking_university_only', 'organization_ranking_university_only', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_sector:actor_sector_append_only', 'organization_sector_append_only', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_strategic_connection_check:actor_strategic_connection_check_append_only', 'organization_strategic_connection_check_append_only', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_topic:actor_topic_no_delete', 'organization_topic_no_delete', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_update_subscription_run:actor_update_subscription_run_append_only', 'organization_update_subscription_run_append_only', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_verification_event:actor_verification_event_append_only', 'organization_verification_event_append_only', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization_verification_event:actor_verification_event_project_status', 'organization_verification_event_project_status', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization:actor_ghus_notes_guard', 'organization_ghus_notes_guard', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization:actor_no_delete', 'organization_no_delete', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition, taken_at) VALUES ('720', 'rename:trigger:organization:actor_status_verification_guard', 'organization_status_verification_guard', '2026-11-24T14:54:24.027206+00:00') ON CONFLICT (migration_id, object_name) DO NOTHING;

COMMIT;
