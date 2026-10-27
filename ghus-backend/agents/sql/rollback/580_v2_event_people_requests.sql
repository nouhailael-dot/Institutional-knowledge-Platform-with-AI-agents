-- Roll back 580. Refuses if any event or people request exists, rather than
-- silently turning it into an actor request.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM actor_update_subscription
               WHERE discovery_entity <> 'actor') THEN
        RAISE EXCEPTION
            '580 rollback refused: event or people requests exist. '
            'Cancel or migrate them first; a rollback never deletes a request.';
    END IF;
END $$;

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_entity_via,
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_discovery_options,
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_entity;

ALTER TABLE actor_update_subscription
    DROP COLUMN IF EXISTS discovery_options,
    DROP COLUMN IF EXISTS discovery_entity;

COMMIT;
