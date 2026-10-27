-- Roll back 590. Refuses while any import verification exists: those events
-- are evidence and are never deleted.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM actor_verification_event
               WHERE decision_origin = 'ghus_import') THEN
        RAISE EXCEPTION
            '590 rollback refused: ghus_import verifications exist and are append-only.';
    END IF;
END $$;

ALTER TABLE actor_verification_event
    DROP CONSTRAINT IF EXISTS ck_actor_verification_event_origin;
ALTER TABLE actor_verification_event
    ADD CONSTRAINT ck_actor_verification_event_origin CHECK (
        (decision_origin = 'ghus_review'
            AND NULLIF(btrim(decided_by), '') IS NOT NULL
            AND decided_at IS NOT NULL
            AND migration_batch_id IS NULL)
        OR (decision_origin = 'existing_canonical_migration'
            AND decision = 'verified'
            AND decided_by IS NULL
            AND decided_at IS NULL
            AND NULLIF(btrim(migration_batch_id), '') IS NOT NULL
            AND topic_id IS NULL)
        OR (decision_origin = 'agent_auto_accept'
            AND decision = 'verified'
            AND NULLIF(btrim(decided_by), '') IS NOT NULL
            AND decided_at IS NOT NULL
            AND NULLIF(btrim(reason), '') IS NOT NULL
            AND migration_batch_id IS NULL)
    );

COMMENT ON CONSTRAINT ck_actor_verification_event_origin ON actor_verification_event IS
    'ghus_review = a person; existing_canonical_migration = pre-V2 carry-over; '
    'agent_auto_accept = the discovery agent accepted it on score and quality gates '
    '(verify only, reasons required).';

COMMIT;
