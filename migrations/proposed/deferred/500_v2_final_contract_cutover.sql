-- PROPOSAL ONLY. Supersedes 460 under the corrected Phase 12 policy.
-- Fails closed unless the independently reviewed data-loss audit is attested.
BEGIN;
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM architecture_v2_cutover_attestation
    WHERE audit_name='pre_cutover_data_loss_audit' AND passed
  ) THEN
    RAISE EXCEPTION 'pre_cutover_data_loss_audit has not passed';
  END IF;
  -- Re-run the audit on the live data inside this transaction: an attestation
  -- recorded earlier is not enough if anything changed since.
  IF EXISTS (SELECT 1 FROM ghus_pre_cutover_data_loss_audit() WHERE NOT passed) THEN
    RAISE EXCEPTION 'pre_cutover_data_loss_audit fails on the current data';
  END IF;
END $$;

ALTER TABLE actor ALTER COLUMN actor_category SET NOT NULL;
ALTER TABLE actor ALTER COLUMN status SET NOT NULL;
ALTER TABLE actor ALTER COLUMN source_origin SET NOT NULL;
-- category_type remains nullable until GHUS separately approves completeness.

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
             AND table_name='actor' AND column_name='alternate_names')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
             AND table_name='actor' AND column_name='alt_names')
  THEN ALTER TABLE actor RENAME COLUMN alternate_names TO alt_names; END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
             AND table_name='actor' AND column_name='location_city')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
             AND table_name='actor' AND column_name='city')
  THEN ALTER TABLE actor RENAME COLUMN location_city TO city; END IF;
END $$;

-- The transitional legacy<->V2 sync trigger reads actor_type, verification_status
-- and record_status; it must go before those columns can be dropped.
DROP TRIGGER IF EXISTS actor_v2_compat_sync ON actor;
DROP FUNCTION IF EXISTS ghus_sync_actor_v2_compat();
DROP VIEW IF EXISTS actor_v1_compat;
DROP VIEW IF EXISTS staged_record_agent3_compat;
DROP VIEW IF EXISTS actor_profile_current;
ALTER TABLE actor
    DROP COLUMN IF EXISTS actor_type,
    DROP COLUMN IF EXISTS actor_type_raw,
    DROP COLUMN IF EXISTS verification_status,
    DROP COLUMN IF EXISTS record_status,
    DROP COLUMN IF EXISTS state,
    DROP COLUMN IF EXISTS primary_technical_focus,
    DROP COLUMN IF EXISTS technical_approach,
    DROP COLUMN IF EXISTS current_activities,
    DROP COLUMN IF EXISTS technology_ip_notes,
    DROP COLUMN IF EXISTS key_constraints,
    DROP COLUMN IF EXISTS estimated_trl,
    DROP COLUMN IF EXISTS primary_lifecycle_role,
    DROP COLUMN IF EXISTS funding_summary;
-- record_verification keeps person/event decisions until the Phase 14 people and
-- events conversion gives them V2 event tables. Actor decisions live only in
-- actor_verification_event, so no actor row may remain here.
DO $$ BEGIN
  IF to_regclass('public.record_verification') IS NOT NULL THEN
    IF EXISTS (SELECT 1 FROM record_verification WHERE entity_type='actor') THEN
      RAISE EXCEPTION '500 refuses: actor decisions remain in record_verification';
    END IF;
    ALTER TABLE record_verification DROP CONSTRAINT IF EXISTS ck_record_verification_non_actor;
    ALTER TABLE record_verification ADD CONSTRAINT ck_record_verification_non_actor
        CHECK (entity_type <> 'actor');
  END IF;
END $$;
DROP TABLE IF EXISTS organization_hierarchy;
DROP TABLE IF EXISTS actor_profile;
DROP TABLE IF EXISTS actor_capability_fact;
COMMIT;
