-- Rollback of 600_v2_event_person_facts.sql. Export both ledgers first: the
-- facts they hold are lost with them (event_claim is left untouched).
BEGIN;
DROP VIEW IF EXISTS person_fact_current;
DROP VIEW IF EXISTS event_fact_current;
DROP TRIGGER IF EXISTS person_fact_append_only ON person_fact;
DROP TRIGGER IF EXISTS event_fact_append_only ON event_fact;
DROP TABLE IF EXISTS person_fact;
DROP TABLE IF EXISTS event_fact;
COMMIT;
