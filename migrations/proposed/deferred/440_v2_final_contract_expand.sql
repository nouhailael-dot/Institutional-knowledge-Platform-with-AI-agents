-- DEFERRED FINAL-V2 EXPAND. Schema-owner execution only.
-- Adds the clean verification/status contract while legacy readers still exist.
BEGIN;

ALTER TABLE actor ADD COLUMN IF NOT EXISTS status text;

CREATE TABLE IF NOT EXISTS actor_verification_event (
    actor_verification_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    topic_id uuid REFERENCES topic(topic_id),
    decision text NOT NULL CHECK (decision IN ('verified','rejected')),
    decided_by text NOT NULL CHECK (nullif(btrim(decided_by),'') IS NOT NULL),
    decided_at timestamptz NOT NULL DEFAULT now(),
    reason text,
    rejection_reason text,
    source_id uuid REFERENCES source(source_id),
    CHECK (decision <> 'rejected' OR nullif(btrim(rejection_reason),'') IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_actor_verification_event_latest
    ON actor_verification_event(actor_id,topic_id,decided_at DESC,actor_verification_event_id DESC);

DROP TRIGGER IF EXISTS actor_verification_event_append_only ON actor_verification_event;
CREATE TRIGGER actor_verification_event_append_only
BEFORE UPDATE OR DELETE ON actor_verification_event
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

CREATE OR REPLACE FUNCTION ghus_project_actor_verification_status() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
    UPDATE actor SET status=NEW.decision,updated_at=now() WHERE actor_id=NEW.actor_id;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS actor_verification_event_project_status ON actor_verification_event;
CREATE TRIGGER actor_verification_event_project_status
AFTER INSERT ON actor_verification_event
FOR EACH ROW EXECUTE FUNCTION ghus_project_actor_verification_status();

-- Only the GHUS review service may append final verification decisions.
-- Readers can inspect the immutable ledger; no role receives UPDATE or DELETE.
ALTER TABLE actor_verification_event ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS actor_verification_event_read ON actor_verification_event;
DROP POLICY IF EXISTS actor_verification_event_ghus_insert ON actor_verification_event;
CREATE POLICY actor_verification_event_read ON actor_verification_event
    FOR SELECT TO authenticated, service_role USING (true);
CREATE POLICY actor_verification_event_ghus_insert ON actor_verification_event
    FOR INSERT TO service_role WITH CHECK (true);
REVOKE ALL ON actor_verification_event FROM anon, authenticated;
GRANT SELECT ON actor_verification_event TO authenticated;
GRANT SELECT, INSERT ON actor_verification_event TO service_role;
REVOKE UPDATE, DELETE ON actor_verification_event FROM service_role;
REVOKE UPDATE (status, ghus_notes) ON actor FROM anon, authenticated;

ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'verify_actor','category_doubt','geocode_failed','hub_needs_review',
    'hub_radius_overlap','hub_member_outside_radius','hub_center_drift',
    'hub_proposal','possible_duplicate','fact_conflict','pending_update',
    'verify_person','verify_event','identity','affiliation_change',
    -- Transitional bridge kinds remain writable only until migration 450.
    'classification','geocode','hub_assignment','same_topic_overlap','new_hub',
    'pending_human_update'
)) NOT VALID;

COMMIT;
