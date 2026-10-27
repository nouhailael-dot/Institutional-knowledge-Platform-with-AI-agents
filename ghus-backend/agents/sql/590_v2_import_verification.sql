-- Architecture V2 - a GHUS-authorized import may create an actor as Verified.
--
-- Decision (2026-10-26, platform owner): a record GHUS supplies through the
-- Data Feed (spreadsheet or form) may be imported as Verified when the person
-- uploading it is named and attests that they are authorized GHUS staff and
-- that the records come from a GHUS source. Everything else still goes to
-- Review.
--
-- Verification still happens only through actor_verification_event; the
-- status trigger and guard are unchanged. This adds a fourth, explicitly
-- labelled origin so an import can never be mistaken for a reviewer's decision
-- or an agent's:
--
--   ghus_review                  a GHUS person decided in Review
--   existing_canonical_migration carried over from the pre-V2 database
--   agent_auto_accept            the discovery agent's quality decision
--   ghus_import                  a named GHUS uploader's attested import (NEW)
--
-- ghus_import may only VERIFY (never reject), must name the uploader, the time
-- and the provenance (file, row, attestation) in its reason. It does not
-- authorize Deep Pull: that gate reads ghus_review decisions only
-- (agents/collection/deep_pull.py). A reviewer can still reject the actor
-- later in Review: a later ghus_review event supersedes it.
--
-- ORDERING: after 560 (the origin list it extends).
-- ROLLBACK: agents/sql/rollback/590_v2_import_verification.sql
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
        OR (decision_origin = 'ghus_import'
            AND decision = 'verified'
            AND NULLIF(btrim(decided_by), '') IS NOT NULL
            AND decided_at IS NOT NULL
            AND NULLIF(btrim(reason), '') IS NOT NULL
            AND migration_batch_id IS NULL)
    );

COMMENT ON CONSTRAINT ck_actor_verification_event_origin ON actor_verification_event IS
    'ghus_review = a person; existing_canonical_migration = pre-V2 carry-over; '
    'agent_auto_accept = the discovery agent accepted it on score and quality gates '
    '(verify only, reasons required); ghus_import = a named GHUS uploader''s attested '
    'Data Feed import (verify only, provenance in the reason).';

-- Prove the rule bites: an import may not reject, nor verify silently or anonymously.
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
        VALUES (some_actor, 'rejected', 'Uploader', now(), 'x', 'x', 'ghus_import');
        RAISE EXCEPTION 'an import rejection was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO actor_verification_event
            (actor_id, decision, decided_by, decided_at, decision_origin)
        VALUES (some_actor, 'verified', 'Uploader', now(), 'ghus_import');
        RAISE EXCEPTION 'an import verification without provenance was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO actor_verification_event
            (actor_id, decision, decided_by, decided_at, reason, decision_origin)
        VALUES (some_actor, 'verified', ' ', now(), 'x', 'ghus_import');
        RAISE EXCEPTION 'an anonymous import verification was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

COMMIT;
