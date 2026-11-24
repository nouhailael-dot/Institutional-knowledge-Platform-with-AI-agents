-- Rollback 740: removes the 8 event columns and what was filled in them.
-- The free-text `location` was never changed. Then, if 740 is in the ledger:
-- DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '740';

BEGIN;
SET LOCAL lock_timeout = '15s';
ALTER TABLE public.event
    DROP COLUMN venue,
    DROP COLUMN city,
    DROP COLUMN state_code,
    DROP COLUMN country,
    DROP COLUMN region_code,
    DROP COLUMN event_format,
    DROP COLUMN registration_url,
    DROP COLUMN organizer;
COMMIT;
