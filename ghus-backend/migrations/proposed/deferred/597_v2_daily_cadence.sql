-- PROPOSAL ONLY. GHUS decision of 2026-10-29 (Ismail Sabbar): a monitoring
-- request can run daily (Monitor and Update -> New request: Once, Daily,
-- Weekly, Monthly). The two cadence checks gain 'daily'; every value they
-- accepted before is still accepted, so no existing row is affected.
--
-- Until this runs, the page does not offer Daily: the backend reads which
-- cadences ck_actor_update_subscription_cadence accepts and offers only those
-- (agents/collection/discovery_requests.py, _db_cadences).
-- ck_collection_run_cadence was NOT VALID and stays NOT VALID. Idempotent.
BEGIN;

ALTER TABLE actor_update_subscription DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_cadence;
ALTER TABLE actor_update_subscription ADD CONSTRAINT ck_actor_update_subscription_cadence
    CHECK (cadence = ANY (ARRAY['once', 'daily', 'weekly', 'biweekly', 'monthly', 'quarterly']));

ALTER TABLE collection_run DROP CONSTRAINT IF EXISTS ck_collection_run_cadence;
ALTER TABLE collection_run ADD CONSTRAINT ck_collection_run_cadence
    CHECK (cadence IS NULL OR cadence = ANY (ARRAY['once', 'daily', 'weekly', 'biweekly', 'monthly', 'quarterly']))
    NOT VALID;

COMMIT;
