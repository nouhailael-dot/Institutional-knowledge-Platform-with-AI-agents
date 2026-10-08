-- PROPOSAL ONLY. Never executed against the shared database by an agent.
-- Local ghus_v2_*_test databases only. Production DDL needs schema-owner
-- approval, a verified fresh backup, a tested rollback and a coordinated
-- deployment, all outside this change.
--
-- Closes the gaps in docs/architecture_v2_schema_conformance.md.
--
-- Every statement here is ADDITIVE or a GUARD. Nothing is dropped, no column is
-- narrowed, and no existing row is rewritten. Each section names the finding it
-- closes so the audit and the migration can be read together.
--
-- ORDERING: after 190, 230, 300, 330, 360, 370. Independent of 510 and 520.
--
-- SPLIT: the two fixes that ALTER a canonical table (the actor composite
-- foreign key, and hub_actor's membership history) are NOT here. agents/sql
-- never alters actor, hub, hub_actor, event or person - that is the separate
-- migration track, and a test enforces it. They live in
-- migrations/proposed/deferred/545_v2_canonical_conformance.sql.
-- ROLLBACK: agents/sql/rollback/530_v2_conformance_fixes.sql

BEGIN;

-- ===========================================================================
-- F1 (BLOCKING) - collection_run cannot describe a run.
--
-- The table records budget and execution: fetches, money, status. The brief's
-- WS4 needs it to record PROVENANCE: what triggered the run, on whose behalf,
-- with what configuration, and what came out. Without these, WS4's run grouping
-- has to infer the trigger from a description string, and WS6's subscriptions
-- have nowhere to record their own runs.
--
-- initiated_by is deliberately NULLABLE. There is no authenticated identity in
-- the platform yet, and an unknown initiator is recorded as NULL and displayed
-- as "Not Recorded". It is never defaulted and never invented.
-- ===========================================================================
ALTER TABLE collection_run
    ADD COLUMN IF NOT EXISTS trigger_type    text,
    ADD COLUMN IF NOT EXISTS cadence         text,
    ADD COLUMN IF NOT EXISTS initiated_by    text,
    ADD COLUMN IF NOT EXISTS config_snapshot jsonb,
    ADD COLUMN IF NOT EXISTS found_count            integer,
    ADD COLUMN IF NOT EXISTS deduplicated_count     integer,
    ADD COLUMN IF NOT EXISTS staged_count           integer,
    ADD COLUMN IF NOT EXISTS review_item_count      integer;

ALTER TABLE collection_run DROP CONSTRAINT IF EXISTS ck_collection_run_trigger_type;
ALTER TABLE collection_run
    ADD CONSTRAINT ck_collection_run_trigger_type
    CHECK (trigger_type IS NULL OR trigger_type IN
           ('manual', 'subscription', 'scheduled_event', 'migration')) NOT VALID;

ALTER TABLE collection_run DROP CONSTRAINT IF EXISTS ck_collection_run_cadence;
ALTER TABLE collection_run
    ADD CONSTRAINT ck_collection_run_cadence
    CHECK (cadence IS NULL OR cadence IN ('once', 'weekly', 'monthly', 'quarterly')) NOT VALID;

ALTER TABLE collection_run DROP CONSTRAINT IF EXISTS ck_collection_run_counts;
ALTER TABLE collection_run
    ADD CONSTRAINT ck_collection_run_counts
    CHECK (COALESCE(found_count, 0) >= 0 AND COALESCE(deduplicated_count, 0) >= 0
           AND COALESCE(staged_count, 0) >= 0 AND COALESCE(review_item_count, 0) >= 0) NOT VALID;

COMMENT ON COLUMN collection_run.initiated_by IS
    'Who asked for this run. NULL until authentication exists; displayed as '
    '"Not Recorded". Never defaulted, never inferred.';

-- ===========================================================================
-- F14 - the UM6P/OCP master list has nowhere to live.
--
-- Architecture V2 Sept 5.5 describes a list of every UM6P/OCP entity that
-- counts, and a 3-state check per actor and per layer. Migration 300 creates
-- both tables; neither reached the target schema, while entity_edge still
-- allows an object_type of 'strategic_entity'. These are the same definitions,
-- created only if missing.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS strategic_entity (
    strategic_entity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_group        text NOT NULL CHECK (entity_group IN ('OCP', 'UM6P', 'INNOVX')),
    name                text NOT NULL UNIQUE,
    -- "A name with only UM6 - not UM6P - does not count" (5.5). Kept as data so
    -- the rule is checkable rather than remembered.
    match_pattern       text NOT NULL,
    notes               text,
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actor_strategic_connection_check (
    actor_id            uuid NOT NULL REFERENCES actor(actor_id),
    layer               smallint NOT NULL CHECK (layer IN (1, 2, 3)),
    -- The three states 5.5 insists on, named as it names them. "Not found in
    -- what has been read so far" is not a claim that no connection exists.
    state               text NOT NULL CHECK (state IN
                            ('found', 'not_found_in_sources_read', 'not_yet_checked')),
    strategic_entity_id uuid REFERENCES strategic_entity(strategic_entity_id),
    connection_kind     text,
    source_id           uuid REFERENCES source(source_id),
    checked_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id, layer),
    -- A "found" answer must name the entity and cite a source. The other two
    -- states must not pretend to.
    CONSTRAINT ck_strategic_check_found CHECK (
        (state = 'found' AND strategic_entity_id IS NOT NULL AND source_id IS NOT NULL)
        OR (state <> 'found' AND strategic_entity_id IS NULL)
    )
);

-- ===========================================================================
-- F7 (no-delete guards) - the evidence tables are protected, the records are not.
--
-- actor_fact, entity_edge, actor_verification_event and the rest are
-- append-only. The records they describe can still be deleted outright, which
-- would take their evidence with them by cascade or leave it orphaned. "Never
-- overwrite, never delete" has to cover the records too.
-- ===========================================================================
CREATE OR REPLACE FUNCTION ghus_guard_no_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        '% is never deleted: reject the record and keep it, with its reason',
        TG_TABLE_NAME;
END $$;

DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY[
        'actor', 'person', 'event', 'hub', 'hub_actor', 'actor_topic', 'actor_location'
    ] LOOP
        IF to_regclass('public.' || target) IS NOT NULL THEN
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', target || '_no_delete', target);
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE DELETE ON %I '
                'FOR EACH ROW EXECUTE FUNCTION ghus_guard_no_delete()',
                target || '_no_delete', target
            );
        END IF;
    END LOOP;
END $$;

-- ===========================================================================
-- F11 - a ranking may only sit on a university actor.
--
-- Architecture V2 Sept 5.2 collects rankings for universities only, and a
-- department never inherits its university's ranking. light_pull.py enforces
-- it; nothing in the schema did, so a direct writer could still insert one.
-- ===========================================================================
CREATE OR REPLACE FUNCTION ghus_guard_ranking_is_university() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE category text;
BEGIN
    SELECT a.actor_category INTO category FROM actor a WHERE a.actor_id = NEW.actor_id;
    IF category IS DISTINCT FROM 'university_academic' THEN
        RAISE EXCEPTION
            'rankings are recorded for university actors only; actor % is %',
            NEW.actor_id, COALESCE(category, 'unclassified');
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS actor_ranking_university_only ON actor_ranking;
CREATE TRIGGER actor_ranking_university_only
    BEFORE INSERT ON actor_ranking
    FOR EACH ROW EXECUTE FUNCTION ghus_guard_ranking_is_university();

-- ===========================================================================
-- F7 (people) - people have no separate verification record.
--
-- Architecture V2 Sept 5.3 gives people their own records and their own
-- verification. actor_verification_event covers actors only. Person discovery
-- is disabled, so nothing writes this yet; it exists so that enabling discovery
-- does not require a schema change first.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS person_verification_event (
    person_verification_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id         uuid NOT NULL REFERENCES person(person_id),
    decision          text NOT NULL CHECK (decision IN ('verified', 'rejected')),
    decided_by        text,
    decided_at        timestamptz,
    reason            text,
    rejection_reason  text,
    source_id         uuid REFERENCES source(source_id),
    decision_origin   text NOT NULL,
    migration_batch_id uuid,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    -- The same honesty rule actor_verification_event carries: a GHUS review
    -- names a reviewer and a date; a migration names its batch and claims
    -- neither. No fake reviewer, no fake date.
    CONSTRAINT ck_person_verification_origin CHECK (
        (decision_origin = 'ghus_review' AND NULLIF(btrim(decided_by), '') IS NOT NULL
         AND decided_at IS NOT NULL AND migration_batch_id IS NULL)
        OR (decision_origin <> 'ghus_review' AND migration_batch_id IS NOT NULL)
    ),
    CONSTRAINT ck_person_verification_rejection CHECK (
        decision <> 'rejected' OR NULLIF(btrim(rejection_reason), '') IS NOT NULL
    )
);

DROP TRIGGER IF EXISTS person_verification_event_append_only ON person_verification_event;
CREATE TRIGGER person_verification_event_append_only
    BEFORE UPDATE OR DELETE ON person_verification_event
    FOR EACH ROW EXECUTE FUNCTION ghus_guard_no_delete();

-- ===========================================================================
-- F13 (ghus_notes) - GHUS-only free text is only protected by convention.
--
-- "GHUS notes - free text, written only by GHUS" (5.1), and for events
-- "the GHUS Event Notes area is never written by the agent" (brief WS2). The
-- agents do not write them, but nothing stopped them. This refuses any change
-- to the column from a session that has not declared itself GHUS.
--
-- The declaration is a session setting, so an agent process simply never sets
-- it; it is a guard rail, not an authentication system. Real authentication is
-- P3 and replaces this.
-- ===========================================================================
CREATE OR REPLACE FUNCTION ghus_guard_notes_column() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.ghus_notes IS DISTINCT FROM OLD.ghus_notes
       AND COALESCE(current_setting('ghus.actor_is_human', true), 'off') <> 'on' THEN
        RAISE EXCEPTION
            '%.ghus_notes is written only by GHUS', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS actor_ghus_notes_guard ON actor;
CREATE TRIGGER actor_ghus_notes_guard
    BEFORE UPDATE OF ghus_notes ON actor
    FOR EACH ROW EXECUTE FUNCTION ghus_guard_notes_column();

DROP TRIGGER IF EXISTS event_ghus_notes_guard ON event;
CREATE TRIGGER event_ghus_notes_guard
    BEFORE UPDATE OF ghus_notes ON event
    FOR EACH ROW EXECUTE FUNCTION ghus_guard_notes_column();

-- ===========================================================================
-- Hub membership keys on SECTOR (GHUS decision, 2026-10-08).
--
-- The evidence tables have to be able to say which dimension decided, or a
-- reviewer reading a stored assignment cannot tell whether the sector or the
-- topic was the gate. Both are recorded on every evaluation; these columns say
-- which one was decisive.
--
-- hub_assignment_evidence and proposed_hub are not canonical record tables, so
-- they belong in this track.
-- ===========================================================================
ALTER TABLE hub_assignment_evidence
    ADD COLUMN IF NOT EXISTS sector_matched boolean,
    ADD COLUMN IF NOT EXISTS dimension      text;

ALTER TABLE hub_assignment_evidence DROP CONSTRAINT IF EXISTS ck_hub_assignment_dimension;
ALTER TABLE hub_assignment_evidence
    ADD CONSTRAINT ck_hub_assignment_dimension
    CHECK (dimension IS NULL OR dimension IN ('sector', 'topic')) NOT VALID;

-- The outcome vocabulary gains the sector verdict. Found by running the Phase
-- 3-7 integration test against a real database: the existing CHECK allowed only
-- the topic verdict, so every sector-gated evaluation was rejected on insert.
ALTER TABLE hub_assignment_evidence DROP CONSTRAINT IF EXISTS hub_assignment_evidence_outcome_check;
ALTER TABLE hub_assignment_evidence
    ADD CONSTRAINT hub_assignment_evidence_outcome_check
    CHECK (outcome IN ('assigned', 'needs_review_sector', 'needs_review_topic',
                       'needs_review_location', 'legacy_membership_preserved'));

-- ck_hub_assignment_evidence_topic_order encoded the OLD rule: location is only
-- evaluated when the TOPIC matched. Under the sector rule, location is
-- evaluated when the SECTOR matched and the topic may well differ -- which is
-- the whole point of the change. The replacement keeps the ordering guarantee
-- (Test 2 never runs unless Test 1 passed) against whichever test was Test 1.
--
-- A legacy row has dimension NULL and keeps the original meaning exactly.
ALTER TABLE hub_assignment_evidence DROP CONSTRAINT IF EXISTS ck_hub_assignment_evidence_topic_order;
ALTER TABLE hub_assignment_evidence
    ADD CONSTRAINT ck_hub_assignment_evidence_gate_order
    CHECK (
        NOT location_evaluated
        OR (dimension IS DISTINCT FROM 'sector' AND topic_matched)
        OR (dimension = 'sector' AND sector_matched)
    );

COMMENT ON COLUMN hub_assignment_evidence.topic_matched IS
    'Whether the actor topic matched the hub topic. Still recorded, but since '
    '2026-10-08 it is secondary: see dimension for what actually decided.';

ALTER TABLE proposed_hub
    ADD COLUMN IF NOT EXISTS dimension     text,
    ADD COLUMN IF NOT EXISTS dimension_key text,
    -- Every topic the proposed members carry, with counts. Secondary evidence:
    -- it says what the cluster works on without having decided who is in it.
    ADD COLUMN IF NOT EXISTS topic_mix     jsonb;

ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS ck_proposed_hub_dimension;
ALTER TABLE proposed_hub
    ADD CONSTRAINT ck_proposed_hub_dimension
    CHECK (dimension IS NULL OR dimension IN ('sector', 'topic')) NOT VALID;

-- ===========================================================================
-- Post-apply assertions.
-- ===========================================================================
DO $$
DECLARE missing text;
BEGIN
    SELECT string_agg(name, ', ') INTO missing FROM (
        SELECT 'collection_run.trigger_type' AS name
        WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name = 'collection_run' AND column_name = 'trigger_type')
        UNION ALL
        SELECT 'strategic_entity' WHERE to_regclass('public.strategic_entity') IS NULL
        UNION ALL
        SELECT 'person_verification_event'
        WHERE to_regclass('public.person_verification_event') IS NULL
    ) AS checks;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'conformance fixes did not apply: %', missing;
    END IF;
END $$;

COMMIT;

-- NOT DONE HERE, on purpose:
--   * VALIDATE on the NOT VALID constraints. Each one scans the whole table and
--     may fail on legacy rows, so each is a separate, deliberate step once the
--     data behind it has been reviewed.
--   * Retiring actor.verification_status. Three status columns and a sync
--     trigger is transitional by design; removing it belongs after cutover.
--   * Backfilling anything at all.
