-- PROPOSAL for the schema owner: record deletion with 30-day retention (approved by
-- GHUS on 17 Nov 2026). Never executed on shared Supabase by an agent; apply after
-- explicit approval, a fresh backup, and a ledger entry. Requires 700 (schema compass).
--
-- Policy: a deleted organization, person, event or hub disappears from active use at
-- once, waits 30 days under Pending Deletion (restorable; separate from Review's Rejected), then the
-- scheduled cleanup removes its canonical data permanently.
--
--   compass.deleted_record     one row per deletion: who, when, why, the deadline,
--                              restore or purge; the row as it was (snapshot)
--   compass.purge_door_open()  true only inside the approved writer's transaction
--                              that purges one deletion whose 30 days are over
--   ghus_guard_no_delete, ghus_reject_mutation, ghus_guard_sector_link_append_only,
--   ghus_guard_subscription_run_append_only
--                              unchanged, except that a DELETE passes while that door
--                              is open; UPDATE is still refused everywhere
--   actor_read                 also hides organizations awaiting permanent deletion
--
-- Nothing is deleted by this migration. Verification history is not touched.
-- ROLLBACK: migrations/proposed/deferred/rollback/710_record_deletion_retention.sql
--           (restores the saved definitions in compass.migration_snapshot exactly)

BEGIN;

-- Fail closed on drift: 710 replaces the four guards and actor_read, and its rollback
-- restores them as they are on production (checked on a restore of the 5 Nov 2026
-- Supabase backup). If any differs here, stop: nothing is changed.
DO $pre$
DECLARE
    found text;
BEGIN
    IF to_regclass('compass.user_profile') IS NULL THEN
        RAISE EXCEPTION '710 needs migration 700 (compass.user_profile)';
    END IF;
    SELECT string_agg(proname || '=' || md5(prosrc), ' ' ORDER BY proname) INTO found
      FROM pg_proc WHERE pronamespace = 'public'::regnamespace
       AND proname IN ('ghus_guard_no_delete', 'ghus_reject_mutation',
                       'ghus_guard_sector_link_append_only', 'ghus_guard_subscription_run_append_only');
    IF found IS DISTINCT FROM
       'ghus_guard_no_delete=50d5a4d149ae6ddab671711995f74503 '
       'ghus_guard_sector_link_append_only=9085b6f48d8b09b4b0c1e2dca80f7ee8 '
       'ghus_guard_subscription_run_append_only=437b46f7461d47c29f76a81c36784b89 '
       'ghus_reject_mutation=6738d523481ae9fa0efd0792f3c45fa8' THEN
        RAISE EXCEPTION '710: the delete guards differ from production as reviewed (%); stop', found;
    END IF;
    SELECT md5(string_agg(column_name || ':' || data_type, ',' ORDER BY ordinal_position)) INTO found
      FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'actor_read';
    IF found IS DISTINCT FROM '22020ae7a529542d7c1e04d3ff6783fb' THEN
        RAISE EXCEPTION '710: actor_read differs from production as reviewed (%); stop', found;
    END IF;
END $pre$;

-- The exact definitions 710 replaces, kept so the rollback restores them byte for byte
-- (production's guard bodies were stored with Windows line endings, which no committed
-- LF file can reproduce).
CREATE TABLE compass.migration_snapshot (
    migration_id text NOT NULL,
    object_name  text NOT NULL,
    definition   text NOT NULL,
    taken_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (migration_id, object_name)
);
ALTER TABLE compass.migration_snapshot ENABLE ROW LEVEL SECURITY;
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition)
SELECT '710', 'public.' || p.proname || '()', pg_get_functiondef(p.oid)
  FROM pg_proc p
 WHERE p.pronamespace = 'public'::regnamespace
   AND p.proname IN ('ghus_guard_no_delete', 'ghus_reject_mutation',
                     'ghus_guard_sector_link_append_only', 'ghus_guard_subscription_run_append_only');
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition)
VALUES ('710', 'public.actor_read',
        'CREATE OR REPLACE VIEW public.actor_read AS ' || pg_get_viewdef('public.actor_read'::regclass));

CREATE TABLE compass.deleted_record (
    deletion_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type  text NOT NULL CHECK (entity_type IN ('actor', 'person', 'event', 'hub')),
    entity_id    uuid NOT NULL,
    name         text NOT NULL,
    snapshot     jsonb NOT NULL,                        -- the row and its links, as deleted
    reason       text CHECK (reason IS NULL OR char_length(reason) <= 500),
    deleted_by   uuid NOT NULL REFERENCES compass.user_profile(user_id),
    deleted_at   timestamptz NOT NULL DEFAULT now(),
    purge_after  timestamptz NOT NULL,
    restored_at  timestamptz,
    restored_by  uuid REFERENCES compass.user_profile(user_id),
    purged_at    timestamptz,
    purge_report jsonb,
    CHECK (purge_after >= deleted_at + interval '30 days'),
    CHECK (restored_at IS NULL OR purged_at IS NULL),
    CHECK ((restored_at IS NULL) = (restored_by IS NULL)),
    CHECK (restored_at IS NULL OR restored_at < purge_after),
    CHECK (purged_at IS NULL OR purged_at >= purge_after)
);
-- At most one pending deletion per record.
CREATE UNIQUE INDEX deleted_record_pending_key ON compass.deleted_record (entity_type, entity_id)
    WHERE restored_at IS NULL AND purged_at IS NULL;
CREATE INDEX deleted_record_due_idx ON compass.deleted_record (purge_after)
    WHERE restored_at IS NULL AND purged_at IS NULL;
ALTER TABLE compass.deleted_record ENABLE ROW LEVEL SECURITY;

-- A deletion row only ever changes once: restored (before its deadline), or purged
-- (after it, when the snapshot is reduced to the minimum kept). Never deleted.
CREATE FUNCTION compass.guard_deleted_record() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'compass.deleted_record is kept permanently';
    END IF;
    IF OLD.restored_at IS NOT NULL OR OLD.purged_at IS NOT NULL THEN
        RAISE EXCEPTION 'deletion % is closed', OLD.deletion_id;
    END IF;
    IF (NEW.deletion_id, NEW.entity_type, NEW.entity_id, NEW.deleted_by, NEW.deleted_at, NEW.purge_after,
        NEW.reason) IS DISTINCT FROM
       (OLD.deletion_id, OLD.entity_type, OLD.entity_id, OLD.deleted_by, OLD.deleted_at, OLD.purge_after,
        OLD.reason) THEN
        RAISE EXCEPTION 'a deletion''s who, when, why and deadline never change';
    END IF;
    IF NEW.restored_at IS NOT NULL AND NEW.purged_at IS NULL THEN
        IF NEW.snapshot IS DISTINCT FROM OLD.snapshot OR NEW.name IS DISTINCT FROM OLD.name THEN
            RAISE EXCEPTION 'a restore does not change the snapshot';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.purged_at IS NOT NULL AND NEW.restored_at IS NULL AND NEW.purged_at >= OLD.purge_after THEN
        RETURN NEW;                                      -- snapshot reduced to the minimum kept
    END IF;
    RAISE EXCEPTION 'a deletion is only restored or purged';
END $$;
CREATE TRIGGER deleted_record_guard BEFORE UPDATE OR DELETE ON compass.deleted_record
    FOR EACH ROW EXECUTE FUNCTION compass.guard_deleted_record();

-- The one door: the purging transaction names its deletion (SET LOCAL
-- ghus.permanent_delete = '<deletion_id>'), and that deletion must be pending and due.
CREATE FUNCTION compass.purge_door_open() RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM compass.deleted_record d
         WHERE d.deletion_id::text = COALESCE(current_setting('ghus.permanent_delete', true), '')
           AND d.restored_at IS NULL AND d.purged_at IS NULL AND d.purge_after <= now())
$$;

CREATE OR REPLACE FUNCTION public.ghus_guard_no_delete()
 RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF TG_OP = 'DELETE' AND compass.purge_door_open() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION
        '% is never deleted: reject the record and keep it, with its reason',
        TG_TABLE_NAME;
END $function$;

CREATE OR REPLACE FUNCTION public.ghus_reject_mutation()
 RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF TG_OP = 'DELETE' AND compass.purge_door_open() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$function$;

CREATE OR REPLACE FUNCTION public.ghus_guard_sector_link_append_only()
 RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF TG_OP = 'DELETE' AND compass.purge_door_open() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only: % is not permitted', TG_TABLE_NAME, TG_OP;
END $function$;

CREATE OR REPLACE FUNCTION public.ghus_guard_subscription_run_append_only()
 RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF TG_OP = 'DELETE' AND compass.purge_door_open() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'actor_update_subscription_run is append-only: % is not permitted', TG_OP;
END $function$;

-- The organizations' read surface also hides those awaiting permanent deletion.
CREATE OR REPLACE VIEW actor_read AS
SELECT a.actor_id, a.name, a.slug, a.actor_category, a.category_type, a.category_note,
       a.category_needs_review, a.description, a.website, a.website_domain,
       a.city, a.state_code, a.region_code, a.country,
       a.latitude, a.longitude, a.is_multi_location, a.status, a.source_origin,
       a.source_id, a.merged_into_actor_id, a.alt_names,
       a.created_at, a.updated_at,
       f.primary_technical_focus, f.technical_approach, f.current_activities,
       f.technology_ip_notes, f.key_constraints, f.funding_summary,
       f.estimated_trl::smallint AS estimated_trl, f.primary_lifecycle_role
FROM actor a
LEFT JOIN LATERAL (
    SELECT max(fact_value #>> '{}') FILTER (WHERE fact_key='primary_technical_focus') primary_technical_focus,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='technical_approach') technical_approach,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='current_activities') current_activities,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='technology_ip_notes') technology_ip_notes,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='key_constraints') key_constraints,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='funding_summary') funding_summary,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='estimated_trl') estimated_trl,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='primary_lifecycle_role') primary_lifecycle_role
    FROM actor_fact
    WHERE actor_fact.actor_id = a.actor_id AND fact_type = 'legacy_baseline'
) f ON true
WHERE a.status IS DISTINCT FROM 'rejected'
  AND NOT EXISTS (SELECT 1 FROM compass.deleted_record d
                   WHERE d.entity_type = 'actor' AND d.entity_id = a.actor_id
                     AND d.restored_at IS NULL AND d.purged_at IS NULL);

COMMIT;
