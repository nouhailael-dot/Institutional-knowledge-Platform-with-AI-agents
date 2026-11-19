-- Rollback for 710_record_deletion_retention.sql. Refuses while any deletion exists
-- (a pending record would reappear at once; a purged one's history is kept).
-- Restores the four guards and actor_read exactly as they were before 710: the
-- definitions 710 saved in compass.migration_snapshot, byte for byte.

BEGIN;

DO $chk$
DECLARE
    saved record;
BEGIN
    IF EXISTS (SELECT 1 FROM compass.deleted_record) THEN
        RAISE EXCEPTION '710 rollback: compass.deleted_record holds deletions; kept';
    END IF;
    IF (SELECT count(*) FROM compass.migration_snapshot WHERE migration_id = '710') <> 5 THEN
        RAISE EXCEPTION '710 rollback: the saved definitions are incomplete; stop';
    END IF;
    FOR saved IN SELECT definition FROM compass.migration_snapshot
                  WHERE migration_id = '710' ORDER BY object_name LOOP
        EXECUTE saved.definition;
    END LOOP;
END $chk$;

DROP FUNCTION compass.purge_door_open();
DROP TABLE compass.deleted_record;
DROP FUNCTION compass.guard_deleted_record();
DROP TABLE compass.migration_snapshot;

COMMIT;
