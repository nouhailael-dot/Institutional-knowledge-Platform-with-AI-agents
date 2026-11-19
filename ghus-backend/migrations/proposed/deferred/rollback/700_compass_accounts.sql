-- Rollback for 700_compass_accounts.sql. Refuses while any account, audit entry,
-- ownership row or usage record exists, so no history is lost by accident.
-- Supabase Auth identities (auth.users) are not touched.

BEGIN;

DO $chk$
BEGIN
    IF EXISTS (SELECT 1 FROM compass.user_profile)
       OR EXISTS (SELECT 1 FROM compass.audit_event)
       OR EXISTS (SELECT 1 FROM compass.record_owner)
       OR EXISTS (SELECT 1 FROM compass.usage_event) THEN
        RAISE EXCEPTION '700 rollback: compass holds accounts or history; kept';
    END IF;
END $chk$;

DROP SCHEMA compass CASCADE;

COMMIT;
