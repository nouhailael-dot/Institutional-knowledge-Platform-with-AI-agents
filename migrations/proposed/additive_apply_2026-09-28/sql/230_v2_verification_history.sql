-- PROPOSAL ONLY. Append-only GHUS verification decisions.
BEGIN;

CREATE TABLE IF NOT EXISTS record_verification (
    verification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type text NOT NULL CHECK (entity_type IN ('actor','person','event','hub')),
    entity_id uuid NOT NULL,
    decision text NOT NULL CHECK (decision IN ('verified','rejected','parked','imported')),
    decided_by text NOT NULL CHECK (nullif(btrim(decided_by),'') IS NOT NULL),
    decided_at timestamptz NOT NULL DEFAULT now(),
    notes text,
    rejection_reason text,
    topic_id uuid REFERENCES topic(topic_id),
    source_id uuid REFERENCES source(source_id),
    CHECK (decision <> 'rejected' OR nullif(btrim(rejection_reason),'') IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_record_verification_entity
    ON record_verification(entity_type,entity_id,decided_at DESC);

CREATE OR REPLACE FUNCTION ghus_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS record_verification_append_only ON record_verification;
CREATE TRIGGER record_verification_append_only
BEFORE UPDATE OR DELETE ON record_verification
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

COMMIT;
-- ROLLBACK: export history, drop trigger/table; retain ghus_reject_mutation if used later.
