-- Roll back 570. Restores the 550 constraints exactly. Refuses if any actor
-- update request exists, rather than silently deleting it.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM actor_update_subscription
               WHERE requested_via = 'actor_updates') THEN
        RAISE EXCEPTION
            '570 rollback refused: actor update requests exist. '
            'Cancel or migrate them first; a rollback never deletes a request.';
    END IF;
END $$;

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_update_request,
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_max_usd,
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_options;

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_via;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_via
    CHECK (requested_via IN ('map_verification', 'review_updates', 'discovery_page'));

ALTER TABLE actor_update_subscription
    DROP COLUMN IF EXISTS max_usd_per_run,
    DROP COLUMN IF EXISTS update_options;

COMMIT;
