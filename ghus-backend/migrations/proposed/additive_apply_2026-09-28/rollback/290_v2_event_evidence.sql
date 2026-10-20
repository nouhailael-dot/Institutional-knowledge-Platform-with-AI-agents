BEGIN;
DROP TRIGGER IF EXISTS event_claim_append_only ON event_claim;
DROP TABLE IF EXISTS event_claim;
DROP TABLE IF EXISTS event_topic;
COMMIT;
