-- Architecture V2 - actor discovery runs only when a person asks for it.
--
-- Until now the weekly job swept for actors on its own, choosing the thinnest
-- existing hubs and searching around them. Discovery now runs only for an
-- explicit request made on the Discovery page: a topic and sub-topic, an area,
-- a period and a frequency - "for three months, keep me updated on energy
-- actors in the Northeast".
--
-- A request is an actor_update_subscription (WS6, migration 540); this adds
-- what a discovery request needs on top of it. Additive only: no column is
-- renamed or dropped, and every existing row stays valid.
--
-- Local isolated test databases only. Production needs schema-owner approval.

BEGIN;

ALTER TABLE actor_update_subscription
    -- What the person called it, shown back to them on the Discovery page.
    ADD COLUMN IF NOT EXISTS title text,
    -- The sub-topic: concrete terms that narrow the topic. "Energy" plus
    -- {battery storage, grid modernisation} searches for those, not for energy
    -- in general.
    ADD COLUMN IF NOT EXISTS focus_terms text[] NOT NULL DEFAULT '{}',
    -- A ceiling on new actors one run may stage. Quality over volume, and a
    -- hard bound on cost: one request can never flood the review queue.
    ADD COLUMN IF NOT EXISTS max_new_actors_per_run integer NOT NULL DEFAULT 10;

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_title;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_title
    CHECK (title IS NULL OR char_length(btrim(title)) BETWEEN 1 AND 160);

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_cap;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_cap
    CHECK (max_new_actors_per_run BETWEEN 1 AND 50);

ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_focus_terms;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_focus_terms
    CHECK (cardinality(focus_terms) <= 8);

-- Requests now also come from the Discovery page.
ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_via;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_via
    CHECK (requested_via IN ('map_verification', 'review_updates', 'discovery_page'));

-- Every two weeks is the practical middle between weekly and monthly. There is
-- deliberately no daily: the organisations being mapped do not change daily,
-- and a daily run would spend the budget re-reading the same pages.
ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_cadence;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_cadence
    CHECK (cadence IN ('once', 'weekly', 'biweekly', 'monthly', 'quarterly'));

-- The run record carries the cadence it ran under (530), so it needs the same
-- list. NOT VALID, as 530 made it: the check applies to new rows.
ALTER TABLE collection_run DROP CONSTRAINT IF EXISTS ck_collection_run_cadence;
ALTER TABLE collection_run
    ADD CONSTRAINT ck_collection_run_cadence
    CHECK (cadence IS NULL OR cadence IN ('once', 'weekly', 'biweekly', 'monthly', 'quarterly'))
    NOT VALID;

-- A discovery request must say what it is about. An area alone ("anything in
-- the Northeast") is the unscoped sweep this whole design replaces.
ALTER TABLE actor_update_subscription
    DROP CONSTRAINT IF EXISTS ck_actor_update_subscription_discovery_topic;
ALTER TABLE actor_update_subscription
    ADD CONSTRAINT ck_actor_update_subscription_discovery_topic
    CHECK (
        requested_via <> 'discovery_page'
        -- COALESCE, as in 540: the arrays are nullable, cardinality(NULL) is
        -- NULL, and a CHECK that evaluates to NULL passes. Without it a
        -- request with no topic at all slipped through - caught by the
        -- self-test below on its first run.
        OR COALESCE(cardinality(sector_codes), 0) > 0
        OR COALESCE(cardinality(topic_ids), 0) > 0
    );

COMMENT ON COLUMN actor_update_subscription.focus_terms IS
    'Sub-topic terms that narrow the search within the sector or topic. At most 8.';
COMMENT ON COLUMN actor_update_subscription.max_new_actors_per_run IS
    'Ceiling on new actors one run may stage; bounds review load and cost.';

-- Prove the new rule bites before committing, rather than trusting its text.
DO $$
BEGIN
    BEGIN
        INSERT INTO actor_update_subscription
            (end_date, cadence, requested_via, region_code)
        VALUES (current_date + 30, 'monthly', 'discovery_page', 'northeast');
        RAISE EXCEPTION 'ck_actor_update_subscription_discovery_topic did not refuse a topicless request';
    EXCEPTION WHEN check_violation THEN
        NULL;  -- refused, as it must be
    END;
END $$;

COMMIT;
