-- PROPOSAL ONLY. Phase 6 immutable assignment evidence; no canonical writer.
BEGIN;

CREATE TABLE IF NOT EXISTS hub_assignment_evidence (
    hub_assignment_evidence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    hub_id uuid NOT NULL REFERENCES hub(hub_id),
    topic_id uuid REFERENCES topic(topic_id),
    outcome text NOT NULL CHECK (outcome IN (
        'assigned','needs_review_topic','needs_review_location','legacy_membership_preserved'
    )),
    topic_matched boolean NOT NULL,
    location_evaluated boolean NOT NULL,
    distance_miles numeric(8,2),
    radius_miles numeric(7,2),
    outside_radius boolean NOT NULL,
    selected boolean NOT NULL,
    method_version text NOT NULL,
    evidence jsonb NOT NULL,
    source_id uuid REFERENCES source(source_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_hub_assignment_evidence_distance
        CHECK (location_evaluated OR distance_miles IS NULL),
    CONSTRAINT ck_hub_assignment_evidence_topic_order
        CHECK (topic_matched OR NOT location_evaluated)
);

CREATE INDEX IF NOT EXISTS ix_hub_assignment_evidence_actor
    ON hub_assignment_evidence(actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_hub_assignment_evidence_hub
    ON hub_assignment_evidence(hub_id, created_at DESC);

CREATE TRIGGER trg_hub_assignment_evidence_immutable
BEFORE UPDATE OR DELETE ON hub_assignment_evidence
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

COMMIT;
