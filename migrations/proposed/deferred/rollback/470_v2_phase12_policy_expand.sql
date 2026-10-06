BEGIN;
DROP TRIGGER IF EXISTS actor_status_verification_guard ON actor;
DROP FUNCTION IF EXISTS ghus_guard_actor_status();
DROP TRIGGER IF EXISTS actor_category_migration_audit_append_only
    ON actor_category_migration_audit;
DROP TABLE IF EXISTS architecture_v2_cutover_attestation;
DROP TABLE IF EXISTS actor_category_migration_audit;
DROP INDEX IF EXISTS ux_actor_existing_canonical_bootstrap;
DROP POLICY IF EXISTS actor_verification_event_ghus_insert ON actor_verification_event;
CREATE POLICY actor_verification_event_ghus_insert ON actor_verification_event
    FOR INSERT TO service_role WITH CHECK (true);
ALTER TABLE actor_verification_event
    DROP CONSTRAINT IF EXISTS ck_actor_verification_event_origin,
    DROP COLUMN IF EXISTS decision_origin,
    DROP COLUMN IF EXISTS migration_batch_id,
    DROP COLUMN IF EXISTS recorded_at;
ALTER TABLE actor_verification_event ALTER COLUMN decided_by SET NOT NULL;
ALTER TABLE actor_verification_event ALTER COLUMN decided_at SET NOT NULL;
ALTER TABLE actor_verification_event ADD CHECK (
    nullif(btrim(decided_by),'') IS NOT NULL
);
DROP FUNCTION IF EXISTS ghus_phase12_legacy_category(text);
COMMIT;
