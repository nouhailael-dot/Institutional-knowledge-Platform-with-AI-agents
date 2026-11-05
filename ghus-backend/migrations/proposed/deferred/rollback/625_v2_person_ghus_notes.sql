-- Rollback for 625_v2_person_ghus_notes.sql. Refuses while any person holds
-- GHUS notes, so nothing GHUS wrote is lost.

BEGIN;

DO $chk$
BEGIN
    IF EXISTS (SELECT 1 FROM person WHERE ghus_notes IS NOT NULL) THEN
        RAISE EXCEPTION '625 rollback: person.ghus_notes holds GHUS notes; kept';
    END IF;
END $chk$;

DROP TRIGGER IF EXISTS person_ghus_notes_guard ON person;
ALTER TABLE person DROP COLUMN IF EXISTS ghus_notes;

COMMIT;
