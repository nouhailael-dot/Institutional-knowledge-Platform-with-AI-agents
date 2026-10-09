-- ROLLBACK for agents/sql/540_v2_actor_update_subscription.sql.
-- Local ghus_v2_*_test databases only.
--
-- Refuses to run once any subscription or run exists: those rows are a record
-- of what GHUS asked for and what came back. Export them first if they are
-- genuinely to be removed.

BEGIN;

DO $$
DECLARE held integer;
BEGIN
    SELECT (SELECT count(*) FROM actor_update_subscription)
         + (SELECT count(*) FROM actor_update_subscription_run)
      INTO held;
    IF held <> 0 THEN
        RAISE EXCEPTION
            'refusing to roll back: % subscription row(s) exist. Export them first.', held;
    END IF;
END $$;

DROP TRIGGER IF EXISTS actor_update_subscription_run_append_only
    ON actor_update_subscription_run;
DROP FUNCTION IF EXISTS ghus_guard_subscription_run_append_only();
DROP TABLE IF EXISTS actor_update_subscription_run;
DROP TABLE IF EXISTS actor_update_subscription;

COMMIT;
