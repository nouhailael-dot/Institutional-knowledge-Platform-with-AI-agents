-- Roll back 560. Refuses while any agent verification exists: those events are
-- evidence and are never deleted.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM actor_verification_event
               WHERE decision_origin = 'agent_auto_accept') THEN
        RAISE EXCEPTION
            '560 rollback refused: agent_auto_accept verifications exist and are append-only.';
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
    );

COMMIT;
