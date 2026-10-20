-- PROPOSAL ONLY. General review queue for duplicates, conflicts, hubs, and geocoding.
BEGIN;

CREATE TABLE IF NOT EXISTS review_item (
    review_item_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    review_kind text NOT NULL CHECK (review_kind IN (
        'possible_duplicate','fact_conflict','pending_human_update','classification',
        'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub'
    )),
    entity_type text NOT NULL,
    entity_id uuid,
    candidate_entity_id uuid,
    topic_id uuid REFERENCES topic(topic_id),
    priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','resolved')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_item_decision (
    review_item_decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    review_item_id uuid NOT NULL REFERENCES review_item(review_item_id),
    decision text NOT NULL CHECK (decision IN ('approve','reject','resolve','defer')),
    decided_by text NOT NULL,
    reason text,
    decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_review_item_queue
    ON review_item(status,review_kind,priority,created_at);

DROP TRIGGER IF EXISTS review_item_decision_append_only ON review_item_decision;
CREATE TRIGGER review_item_decision_append_only BEFORE UPDATE OR DELETE ON review_item_decision
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
COMMIT;
-- ROLLBACK: export decisions/items, drop both tables.
