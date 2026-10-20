-- PROPOSAL ONLY. People stay disabled until documented supervisor approval.
BEGIN;
CREATE TABLE IF NOT EXISTS person_topic (
    person_id uuid NOT NULL REFERENCES person(person_id),
    topic_id uuid NOT NULL REFERENCES topic(topic_id),
    expertise_summary text NOT NULL,
    source_id uuid NOT NULL REFERENCES source(source_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (person_id,topic_id,source_id)
);
CREATE TABLE IF NOT EXISTS contact_collection_authorization (
    authorization_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid REFERENCES person(person_id),
    requested_by text NOT NULL,
    request_text text NOT NULL,
    official_public_only boolean NOT NULL DEFAULT true CHECK (official_public_only),
    created_at timestamptz NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS contact_collection_authorization_append_only ON contact_collection_authorization;
CREATE TRIGGER contact_collection_authorization_append_only
BEFORE UPDATE OR DELETE ON contact_collection_authorization
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
COMMIT;
