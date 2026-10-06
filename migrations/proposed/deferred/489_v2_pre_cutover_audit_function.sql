-- PROPOSAL ONLY. Pre-cutover data-loss audit as a database function.
-- Lets the schema owner run the exact audit on the production database
-- (read-only) and lets migration 500 re-check it inside its own transaction.
-- Every legacy value that 500 removes must have a destination row or an explicit
-- legacy_migration_record; row counts must match the baseline captured before
-- the cutover started. No check is ever skipped: a missing structure fails.
BEGIN;

CREATE TABLE IF NOT EXISTS architecture_v2_cutover_baseline (
    table_name text PRIMARY KEY,
    row_count bigint NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
-- Rows removed by an explicit GHUS decision are archived here, never silently lost.
CREATE TABLE IF NOT EXISTS hub_actor_removed (
    hub_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    membership jsonb NOT NULL,
    reason text NOT NULL,
    decided_by text NOT NULL,
    removed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hub_id, actor_id)
);
CREATE TABLE IF NOT EXISTS hub_removed (
    hub_id uuid PRIMARY KEY,
    hub jsonb NOT NULL,
    reason text NOT NULL,
    decided_by text NOT NULL,
    removed_at timestamptz NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS hub_actor_removed_append_only ON hub_actor_removed;
CREATE TRIGGER hub_actor_removed_append_only BEFORE UPDATE OR DELETE ON hub_actor_removed
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
DROP TRIGGER IF EXISTS hub_removed_append_only ON hub_removed;
CREATE TRIGGER hub_removed_append_only BEFORE UPDATE OR DELETE ON hub_removed
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

-- First run records the baseline; later runs never overwrite it.
INSERT INTO architecture_v2_cutover_baseline(table_name,row_count)
SELECT 'actor', count(*) FROM actor
UNION ALL SELECT 'hub', count(*) FROM hub
UNION ALL SELECT 'hub_actor', count(*) FROM hub_actor
UNION ALL SELECT 'event', count(*) FROM event
ON CONFLICT (table_name) DO NOTHING;

CREATE OR REPLACE FUNCTION ghus_pre_cutover_data_loss_audit()
RETURNS TABLE(check_name text, source_rows bigint, destination_rows bigint,
              passed boolean, detail jsonb)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  field text;
  n_source bigint;
  n_dest bigint;
  dist_source jsonb;
  dist_dest jsonb;
  status_column text;
BEGIN
  -- 1. Category concept and raw evidence preserved in the migration audit.
  SELECT count(*) INTO n_source FROM actor;
  SELECT count(*) INTO n_dest FROM actor_category_migration_audit;
  check_name := 'actor category concept'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
             AND table_name='actor' AND column_name='actor_type_raw') THEN
    EXECUTE 'SELECT count(actor_type_raw) FROM actor' INTO n_source;
  ELSE n_source := NULL; END IF;
  SELECT count(legacy_category_raw) INTO n_dest FROM actor_category_migration_audit;
  check_name := 'actor.actor_type_raw'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source IS NOT NULL AND n_source = n_dest; detail := '{}'; RETURN NEXT;

  -- 2. Legacy status distribution preserved exactly in prior_status, with an honest
  --    bootstrap event for every actor.
  SELECT CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
              AND table_name='actor' AND column_name='verification_status')
         THEN 'verification_status' ELSE 'record_status' END INTO status_column;
  EXECUTE format('SELECT COALESCE(jsonb_object_agg(v,n),''{}'') FROM (SELECT COALESCE(%I,''<null>'') v,'
                 'count(*) n FROM actor GROUP BY 1) d', status_column) INTO dist_source;
  SELECT COALESCE(jsonb_object_agg(v,n),'{}') INTO dist_dest FROM (
    SELECT COALESCE(prior_status,'<null>') v, count(*) n FROM actor_category_migration_audit GROUP BY 1) d;
  SELECT count(*) INTO n_dest FROM actor_verification_event
   WHERE decision_origin='existing_canonical_migration' AND decision='verified'
     AND decided_by IS NULL AND decided_at IS NULL AND topic_id IS NULL;
  SELECT count(*) INTO n_source FROM actor;
  check_name := 'actor legacy status distribution'; source_rows := n_source;
  destination_rows := n_dest;
  passed := dist_source = dist_dest AND n_dest = n_source;
  detail := jsonb_build_object('legacy', dist_source, 'prior_status', dist_dest);
  RETURN NEXT;

  -- 3. Legacy state: normalized or listed for review, raw value kept.
  EXECUTE 'SELECT count(*) FROM actor WHERE NULLIF(btrim(state),'''') IS NOT NULL' INTO n_source;
  SELECT count(*) INTO n_dest FROM legacy_migration_record
   WHERE legacy_table='actor' AND legacy_field='state' AND disposition IN ('normalized','review');
  check_name := 'actor.state'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  -- 4. Narrative scalar fields: fact row that exists, or explicit audit record.
  FOREACH field IN ARRAY ARRAY['description','primary_technical_focus','technical_approach',
      'current_activities','technology_ip_notes','key_constraints','funding_summary',
      'estimated_trl','primary_lifecycle_role'] LOOP
    EXECUTE format('SELECT count(*) FROM actor WHERE NULLIF(btrim(%I::text),'''') IS NOT NULL', field)
      INTO n_source;
    SELECT count(*) INTO n_dest FROM legacy_migration_record r
     LEFT JOIN actor_fact f ON f.actor_fact_id=r.destination_id
     WHERE r.legacy_table='actor' AND r.legacy_field=field
       AND (r.disposition='audit_only' OR f.actor_fact_id IS NOT NULL);
    check_name := 'actor.' || field; source_rows := n_source; destination_rows := n_dest;
    passed := n_source = n_dest; detail := '{}'; RETURN NEXT;
  END LOOP;

  -- 5. Legacy tables 500 removes or narrows.
  SELECT count(*) INTO n_source FROM record_verification WHERE entity_type='actor';
  check_name := 'record_verification actor decisions'; source_rows := n_source;
  destination_rows := 0; passed := n_source = 0; detail := '{}'; RETURN NEXT;

  SELECT count(*) INTO n_source FROM organization_hierarchy;
  SELECT count(*) INTO n_dest FROM legacy_migration_record r
    JOIN review_item i ON i.review_item_id=r.destination_id
   WHERE r.legacy_table='organization_hierarchy';
  check_name := 'organization_hierarchy'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  SELECT count(*) FILTER (WHERE NULLIF(btrim(profile_summary),'') IS NOT NULL)
       + count(*) FILTER (WHERE NULLIF(btrim(identity_summary),'') IS NOT NULL)
       + count(*) FILTER (WHERE NULLIF(btrim(technical_summary),'') IS NOT NULL)
       + count(*) FILTER (WHERE NULLIF(btrim(lifecycle_summary),'') IS NOT NULL)
       + count(*) FILTER (WHERE NULLIF(btrim(funding_summary),'') IS NOT NULL)
    INTO n_source FROM actor_profile;
  SELECT count(*) INTO n_dest FROM legacy_migration_record r
     LEFT JOIN actor_fact f ON f.actor_fact_id=r.destination_id
   WHERE r.legacy_table='actor_profile' AND (r.disposition='audit_only' OR f.actor_fact_id IS NOT NULL);
  check_name := 'actor_profile values'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  SELECT count(*) INTO n_source FROM actor_capability_fact;
  SELECT count(*) INTO n_dest FROM legacy_migration_record r
     LEFT JOIN actor_fact f ON f.actor_fact_id=r.destination_id
   WHERE r.legacy_table='actor_capability_fact'
     AND (r.disposition='audit_only' OR f.actor_fact_id IS NOT NULL);
  check_name := 'actor_capability_fact'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  -- 6. Row counts unchanged since the cutover baseline, except rows archived by an
  --    explicit GHUS decision (which are counted as accounted for).
  FOR field, n_source IN SELECT table_name, row_count FROM architecture_v2_cutover_baseline LOOP
    EXECUTE format('SELECT count(*) FROM %I', field) INTO n_dest;
    IF field = 'hub' THEN n_dest := n_dest + (SELECT count(*) FROM hub_removed); END IF;
    IF field = 'hub_actor' THEN n_dest := n_dest + (SELECT count(*) FROM hub_actor_removed); END IF;
    check_name := 'row count ' || field; source_rows := n_source; destination_rows := n_dest;
    passed := n_source = n_dest; detail := '{}'; RETURN NEXT;
  END LOOP;
END;
$$;

COMMENT ON FUNCTION ghus_pre_cutover_data_loss_audit() IS
  'Architecture V2 pre-cutover data-loss audit; every row must pass before migration 500.';
COMMIT;
