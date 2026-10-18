-- Roll back 550. Restores the 540 constraints exactly. Refuses if any row now
-- depends on what 550 allowed, rather than silently deleting that request.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM actor_update_subscription
               WHERE requested_via = 'discovery_page' OR cadence = 'biweekly')
       OR EXISTS (SELECT 1 FROM collection_run WHERE cadence = 'biweekly') THEN
        RAISE EXCEPTION
            '550 rollback refused: discovery_page or biweekly requests exist. '
            'Cancel or migrate them first; a rollback never deletes a request.';
    END IF;
END $$;

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_discovery_topic,
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_focus_terms,
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_cap,
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_title;

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_via;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_via
    CHECK (requested_via IN ('map_verification', 'review_updates'));

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_cadence;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_cadence
    CHECK (cadence IN ('once', 'weekly', 'monthly', 'quarterly'));

ALTER TABLE collection_run DROP CONSTRAINT IF EXISTS ck_collection_run_cadence;
ALTER TABLE collection_run
    ADD CONSTRAINT ck_collection_run_cadence
    CHECK (cadence IS NULL OR cadence IN ('once', 'weekly', 'monthly', 'quarterly')) NOT VALID;

ALTER TABLE actor_update_subscription
    DROP COLUMN IF EXISTS max_new_actors_per_run,
    DROP COLUMN IF EXISTS focus_terms,
    DROP COLUMN IF EXISTS title;

COMMIT;
