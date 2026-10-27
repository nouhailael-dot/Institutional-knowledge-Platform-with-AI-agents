-- Architecture V2 - Discovery-page requests for events and people.
--
-- Until now a Discovery-page request (migration 550) always found
-- organizations. A person can now ask for events ("water conferences in the
-- Great Lakes between March and June") or for people ("battery storage
-- researchers at universities in Texas"). Same table, same scheduler
-- (agents/collection/subscription_runner.py), same Review: there is no second
-- request system.
--
-- What a request needs on top of 540/550/570:
--   * discovery_entity  - what the request finds: actor (every existing row),
--                         event or person.
--   * discovery_options - the entity's own scope, validated by
--                         agents/collection/subscriptions.py before it is saved:
--                         events  - date_from, date_to, event_types
--                         people  - institution, role
--
-- Additive only: no column is renamed or dropped, and every existing row stays
-- an actor request (the default) with no options.
--
-- Local isolated test databases only. Production needs schema-owner approval.

BEGIN;

ALTER TABLE actor_update_subscription
    ADD COLUMN IF NOT EXISTS discovery_entity text NOT NULL DEFAULT 'actor',
    ADD COLUMN IF NOT EXISTS discovery_options jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_entity;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_entity
    CHECK (discovery_entity IN ('actor', 'event', 'person'));

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_discovery_options;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_discovery_options
    CHECK (jsonb_typeof(discovery_options) = 'object');

-- Only a Discovery-page request finds events or people; an actor update
-- request always reads actors.
ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_entity_via;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_entity_via
    CHECK (discovery_entity = 'actor' OR requested_via = 'discovery_page');

COMMENT ON COLUMN actor_update_subscription.discovery_entity IS
    'What a Discovery-page request finds: actor, event or person.';
COMMENT ON COLUMN actor_update_subscription.discovery_options IS
    'Event requests: date_from, date_to, event_types. People requests: institution, role.';

DO $$
BEGIN
    -- Prove the new rules bite rather than trusting the CHECK text.
    BEGIN
        INSERT INTO actor_update_subscription
            (end_date, cadence, requested_via, sector_codes, discovery_entity)
        VALUES (current_date, 'once', 'discovery_page', ARRAY['WATER'], 'organisation');
        RAISE EXCEPTION 'an unknown discovery entity was accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
    BEGIN
        INSERT INTO actor_update_subscription
            (end_date, cadence, requested_via, sector_codes, discovery_entity)
        VALUES (current_date, 'once', 'map_verification', ARRAY['WATER'], 'person');
        RAISE EXCEPTION 'a people request outside the Discovery page was accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END $$;

COMMIT;
