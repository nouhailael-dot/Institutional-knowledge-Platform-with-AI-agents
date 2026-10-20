-- PROPOSAL ONLY. Event topics and immutable sourced claims.
BEGIN;
CREATE TABLE IF NOT EXISTS event_topic (
    event_id uuid NOT NULL REFERENCES event(event_id),
    topic_id uuid NOT NULL REFERENCES topic(topic_id),
    why_matched text NOT NULL,
    source_id uuid NOT NULL REFERENCES source(source_id),
    collection_request_id uuid NOT NULL REFERENCES collection_request(collection_request_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id,topic_id,source_id)
);
CREATE TABLE IF NOT EXISTS event_claim (
    event_claim_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL REFERENCES event(event_id),
    claim_text text NOT NULL,
    source_id uuid NOT NULL REFERENCES source(source_id),
    created_at timestamptz NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS event_claim_append_only ON event_claim;
CREATE TRIGGER event_claim_append_only BEFORE UPDATE OR DELETE ON event_claim
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
COMMIT;
