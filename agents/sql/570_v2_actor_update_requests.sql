-- Architecture V2 - actor update requests: keep chosen actors current.
--
-- The Discovery page's "Actor updates" can now be saved as a request: one
-- actor or a bounded group, re-read once or on a frequency (weekly to
-- quarterly), for a stated period. A request is an actor_update_subscription
-- (WS6, migration 540), run by the same request runner as discovery requests
-- (agents/collection/subscription_runner.py); there is no second scheduler.
--
-- What an update request needs on top of 540/550:
--   * update_options  - what to re-read (scope, depth, change categories,
--                        boxes, focus words, actor category, sector for the
--                        facts, actors per run). A JSON object, validated by
--                        agents/collection/actor_updates.py before it is saved.
--   * max_usd_per_run - the spend ceiling for one run. A run stops reading
--                        actors when it is reached.
--   * requested_via 'actor_updates' - so these requests are told apart from
--                        Discovery-page requests.
--
-- Additive only: no column is renamed or dropped, existing rows stay valid
-- (the new column defaults to an empty object and the ceiling is NULL for
-- every request that is not an actor update request).
--
-- Local isolated test databases only. Production needs schema-owner approval.

BEGIN;

ALTER TABLE actor_update_subscription
    ADD COLUMN IF NOT EXISTS update_options jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS max_usd_per_run numeric(8,4);

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_options;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_options
    CHECK (jsonb_typeof(update_options) = 'object');

-- A hard outer bound; the configured per-run ceiling is lower.
ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_max_usd;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_max_usd
    CHECK (max_usd_per_run IS NULL OR (max_usd_per_run > 0 AND max_usd_per_run <= 5));

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_via;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_via
    CHECK (requested_via IN ('map_verification', 'review_updates', 'discovery_page',
                             'actor_updates'));

-- An actor update request always says what to read and what it may spend.
ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_update_request;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_update_request
    CHECK (requested_via <> 'actor_updates'
           OR (max_usd_per_run IS NOT NULL AND update_options ? 'scope'));

COMMENT ON COLUMN actor_update_subscription.update_options IS
    'Actor update requests only: what to re-read (scope, depth, categories, boxes, '
    'focus, actor category, fact sector, actors per run). Empty for other requests.';
COMMENT ON COLUMN actor_update_subscription.max_usd_per_run IS
    'Actor update requests only: the spend ceiling of one run, in USD.';

DO $$
BEGIN
    -- Prove the new rule bites rather than trusting the CHECK text.
    BEGIN
        INSERT INTO actor_update_subscription(end_date, cadence, requested_via, sector_codes)
        VALUES (current_date, 'once', 'actor_updates', ARRAY['WATER']);
        RAISE EXCEPTION 'an actor update request without a spend ceiling was accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END $$;

COMMIT;
