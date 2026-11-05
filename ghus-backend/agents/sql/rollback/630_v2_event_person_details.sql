-- Rollback for 630_v2_event_person_details.sql: remove event_details and
-- person_details. They only mirror event_fact, person_fact and event_claim,
-- which keep every reading, so nothing is lost.

BEGIN;

DROP TRIGGER IF EXISTS event_details_follows_fact ON event_fact;
DROP TRIGGER IF EXISTS person_details_follows_fact ON person_fact;
DROP TRIGGER IF EXISTS event_details_follows_claim ON event_claim;
DROP FUNCTION IF EXISTS ghus_event_details_on_fact();
DROP FUNCTION IF EXISTS ghus_person_details_on_fact();
DROP FUNCTION IF EXISTS ghus_event_details_on_claim();
DROP FUNCTION IF EXISTS ghus_event_details_refresh_claims(uuid);
DROP FUNCTION IF EXISTS ghus_entity_details_refresh(text, uuid, text);
DROP TABLE IF EXISTS event_details;
DROP TABLE IF EXISTS person_details;

COMMIT;
