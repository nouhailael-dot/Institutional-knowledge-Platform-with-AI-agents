-- Architecture V2 - an accepted discovery candidate is created as Verified.
--
-- Decision (2026-10-14): an actor the discovery agent ACCEPTS - score >= the
-- accept threshold AND every quality gate held (agents/discovery/search/
-- actor_quality.py) - is created Verified, not Parked awaiting review.
--
-- Verification still happens only through actor_verification_event; the
-- status trigger and guard are unchanged. This adds a third, explicitly
-- labelled origin so an agent verification can never be mistaken for a
-- person's:
--
--   ghus_review                  a GHUS person decided
--   existing_canonical_migration carried over from the pre-V2 database
--   agent_auto_accept            the discovery agent's quality decision (NEW)
--
-- agent_auto_accept may only VERIFY (never reject), must name the agent and
-- carry its reasons. A person can still reject such an actor later in Review:
-- a later ghus_review event supersedes it, as with any verification.
--
-- Local isolated test databases only. Production needs schema-owner approval.

BEGIN;

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

-- Prove the rule bites: an agent may not reject, and may not verify silently.
DO $$
DECLARE
    some_actor uuid;
BEGIN
    SELECT actor_id INTO some_actor FROM actor LIMIT 1;
    IF some_actor IS NULL THEN
        RETURN;
    END IF;
    BEGIN
        INSERT INTO actor_verification_event
            (actor_id, decision, decided_by, decided_at, reason, rejection_reason, decision_origin)
        VALUES (some_actor, 'rejected', 'discovery-agent', now(), 'x', 'x', 'agent_auto_accept');
        RAISE EXCEPTION 'an agent rejection was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO actor_verification_event
            (actor_id, decision, decided_by, decided_at, decision_origin)
        VALUES (some_actor, 'verified', 'discovery-agent', now(), 'agent_auto_accept');
        RAISE EXCEPTION 'an agent verification without reasons was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

COMMIT;
