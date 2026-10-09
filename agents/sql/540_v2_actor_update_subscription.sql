-- PROPOSAL ONLY. Never executed against the shared database by an agent.
-- Local ghus_v2_*_test databases only. Production DDL needs schema-owner
-- approval, a verified fresh backup, a tested rollback and a coordinated
-- deployment, all outside this change.
--
-- WS6: actor update subscriptions.
--
-- Replaces the default weekly all-sector ACTOR sweep with opt-in, scoped
-- subscriptions. GHUS asks for a specific set of actors, sectors, topics or
-- places to be kept current for a stated period; nothing else is swept.
--
-- The EVENT update schedule is deliberately untouched. Events are time-bound
-- and go stale on their own; actors do not.
--
-- Additive only. Nothing existing is altered or dropped.
--
-- ORDERING: after 190 (source origins), 210 (topics), 260 (collection runs),
-- 520 (sectors). Independent of 510, 530 and 545.
-- ROLLBACK: agents/sql/rollback/540_v2_actor_update_subscription.sql

BEGIN;

CREATE TABLE IF NOT EXISTS actor_update_subscription (
    actor_update_subscription_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Scope. All four are optional and they intersect: a subscription with
    -- sector AGRI and state CA means agriculture actors in California, not
    -- everything in either. A subscription with no scope at all is refused,
    -- because that is the all-sector sweep this replaces.
    actor_ids     uuid[],
    sector_codes  text[],
    topic_ids     uuid[],
    country       text,
    state_code    text REFERENCES region_state(state_code),
    city          text,
    region_code   text REFERENCES region_definition(region_code),

    -- Period. A subscription always ends: an open-ended one is the sweep again
    -- under another name.
    start_date    date NOT NULL DEFAULT current_date,
    end_date      date NOT NULL,
    cadence       text NOT NULL,

    -- Provenance. requested_by is NULLABLE because there is no authenticated
    -- identity yet; an unknown requester is NULL and displays as "Not
    -- Recorded". It is never defaulted to a service account and never inferred.
    requested_by  text,
    requested_via text NOT NULL,
    origin_run_id uuid REFERENCES collection_run(collection_run_id),

    status        text NOT NULL DEFAULT 'active',
    last_run_at   timestamptz,
    next_due_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_actor_update_subscription_cadence
        CHECK (cadence IN ('once', 'weekly', 'monthly', 'quarterly')),
    CONSTRAINT ck_actor_update_subscription_status
        CHECK (status IN ('active', 'paused', 'expired', 'cancelled')),
    CONSTRAINT ck_actor_update_subscription_via
        CHECK (requested_via IN ('map_verification', 'review_updates')),
    CONSTRAINT ck_actor_update_subscription_period
        CHECK (end_date >= start_date),
    -- A subscription must be about something. Without this, the first empty row
    -- silently restores the behaviour this workstream exists to remove.
    CONSTRAINT ck_actor_update_subscription_scope CHECK (
        COALESCE(cardinality(actor_ids), 0) > 0
        OR COALESCE(cardinality(sector_codes), 0) > 0
        OR COALESCE(cardinality(topic_ids), 0) > 0
        OR NULLIF(btrim(COALESCE(country, '')), '') IS NOT NULL
        OR state_code IS NOT NULL
        OR region_code IS NOT NULL
        OR NULLIF(btrim(COALESCE(city, '')), '') IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS ix_actor_update_subscription_due
    ON actor_update_subscription(next_due_at) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS ix_actor_update_subscription_status
    ON actor_update_subscription(status);

COMMENT ON COLUMN actor_update_subscription.requested_by IS
    'Who asked for this subscription. NULL until authentication exists; shown as '
    '"Not Recorded". Never defaulted, never inferred.';
COMMENT ON CONSTRAINT ck_actor_update_subscription_scope
    ON actor_update_subscription IS
    'A subscription with no scope would sweep everything, which is the behaviour '
    'opt-in subscriptions replace.';

-- ---------------------------------------------------------------------------
-- Each run of a subscription links to the collection-run model (WS4), so a
-- discovered actor can always be traced back to the subscription that asked
-- for it and the run that found it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actor_update_subscription_run (
    actor_update_subscription_id uuid NOT NULL
        REFERENCES actor_update_subscription(actor_update_subscription_id),
    collection_run_id uuid NOT NULL REFERENCES collection_run(collection_run_id),
    dry_run    boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_update_subscription_id, collection_run_id)
);

CREATE INDEX IF NOT EXISTS ix_actor_update_subscription_run_run
    ON actor_update_subscription_run(collection_run_id);

-- A subscription run is evidence of what was asked and what came back. It is
-- corrected by adding another run, never by editing or deleting this one.
CREATE OR REPLACE FUNCTION ghus_guard_subscription_run_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'actor_update_subscription_run is append-only: % is not permitted', TG_OP;
END $$;

DROP TRIGGER IF EXISTS actor_update_subscription_run_append_only
    ON actor_update_subscription_run;
CREATE TRIGGER actor_update_subscription_run_append_only
    BEFORE UPDATE OR DELETE ON actor_update_subscription_run
    FOR EACH ROW EXECUTE FUNCTION ghus_guard_subscription_run_append_only();

-- ---------------------------------------------------------------------------
-- Post-apply assertions.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF to_regclass('public.actor_update_subscription') IS NULL
       OR to_regclass('public.actor_update_subscription_run') IS NULL THEN
        RAISE EXCEPTION 'the actor update subscription tables were not created';
    END IF;
    -- Prove the scope rule actually bites, rather than trusting the CHECK text.
    BEGIN
        INSERT INTO actor_update_subscription(end_date, cadence, requested_via)
        VALUES (current_date, 'once', 'review_updates');
        RAISE EXCEPTION 'a subscription with no scope was accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END $$;

COMMIT;

-- NOT DONE HERE, on purpose:
--   * No subscription rows. Each one is a GHUS request, not a default.
--   * No scheduler. The contract is in
--     docs/contracts/actor_update_subscriptions.md; trigger policy, cadence
--     options and ranking weights are configuration values awaiting GHUS
--     sign-off, not constants in code.
--   * The event update schedule is untouched.
