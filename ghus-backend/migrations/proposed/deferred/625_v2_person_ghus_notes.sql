-- PROPOSAL for the schema owner, approved by the platform owner on 5 Nov 2026.
--
-- GHUS Notes for people. Organizations and events have a ghus_notes column
-- ("GHUS notes - free text, written only by GHUS", Architecture V2 section
-- 5.1); people had none, so what GHUS knows about a person (where they met,
-- past conversations, who introduced them) had nowhere to go. Review now shows
-- the GHUS Notes box for people too.
--
-- This alters a canonical table, so it lives in this track, not agents/sql
-- (tests/db/test_architecture_v2_schema.py keeps that separation). The guard
-- is the one migration 530 put on actor and event: only a session that
-- declares itself GHUS (agents.enrichment.decisions.record_ghus_notes) may
-- change the column; an agent never does.
--
-- Additive: one nullable column; no existing row changes.
-- ORDERING: after agents/sql/530 (ghus_guard_notes_column).
-- ROLLBACK: migrations/proposed/deferred/rollback/625_v2_person_ghus_notes.sql

BEGIN;

ALTER TABLE person ADD COLUMN IF NOT EXISTS ghus_notes text
    CHECK (ghus_notes IS NULL OR char_length(ghus_notes) <= 5000);

DROP TRIGGER IF EXISTS person_ghus_notes_guard ON person;
CREATE TRIGGER person_ghus_notes_guard
    BEFORE UPDATE OF ghus_notes ON person
    FOR EACH ROW EXECUTE FUNCTION ghus_guard_notes_column();

COMMIT;
