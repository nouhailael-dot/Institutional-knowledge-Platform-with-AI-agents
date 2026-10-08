-- PROPOSAL ONLY, for the schema owner. Local ghus_v2_*_test databases only.
--
-- The two conformance fixes that ALTER a canonical table. They live in this
-- track, not in agents/sql, because agents/sql never alters actor, hub,
-- hub_actor, event or person -- tests/db/test_architecture_v2_schema.py
-- enforces that separation and it is a good rule.
--
-- Companion: agents/sql/530_v2_conformance_fixes.sql holds everything else
-- (collection_run provenance, the UM6P/OCP master-list tables, the no-delete
-- guards, the ranking rule, person verification, ghus_notes protection).
--
-- Findings closed: F2 and F9 of docs/architecture_v2_schema_conformance.md.
-- ROLLBACK: see the end of this file.

BEGIN;

-- ===========================================================================
-- F2 - the composite category/type foreign key.
--
-- fk_actor_category_type is owned by the deferred cutover chain (380, 450,
-- 490). Until that runs, an invalid category/type pair is impossible in the API
-- and the UI but perfectly storable in the database. This adds it only when it
-- is absent, so the chain and this migration cannot fight over it.
--
-- Added NOT VALID: existing rows are not re-checked, so the statement does not
-- block on a long scan and cannot fail because of legacy data. VALIDATE is a
-- separate, deliberate step once the mapping in
-- docs/evidence/taxonomy_intern_guide_mapping.csv has been applied.
-- ===========================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_actor_category_type'
    ) THEN
        ALTER TABLE actor
            ADD CONSTRAINT fk_actor_category_type
            FOREIGN KEY (actor_category, category_type)
            REFERENCES actor_category_type_definition(category_code, type_code)
            NOT VALID;
    END IF;
END $$;

-- ===========================================================================
-- F9 - hub_actor has no membership history.
--
-- "Historical memberships are never silently replaced, and members outside the
-- radius are flagged, not removed." With no state column that depended on
-- nobody issuing an UPDATE. These columns make supersession explicit, and the
-- partial index keeps exactly one current row per (hub, actor).
-- ===========================================================================
ALTER TABLE hub_actor
    ADD COLUMN IF NOT EXISTS is_current    boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS superseded_at timestamptz,
    ADD COLUMN IF NOT EXISTS superseded_by text,
    ADD COLUMN IF NOT EXISTS assigned_by   text;

ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS ck_hub_actor_superseded;
ALTER TABLE hub_actor
    ADD CONSTRAINT ck_hub_actor_superseded
    CHECK (is_current OR superseded_at IS NOT NULL) NOT VALID;

COMMENT ON COLUMN hub_actor.assigned_by IS
    'The GHUS reviewer who chose this membership by hand, when one did. NULL for '
    'a deterministic assignment. Never defaulted.';

-- ===========================================================================
-- Post-apply assertions.
-- ===========================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_actor_category_type') THEN
        RAISE EXCEPTION 'fk_actor_category_type was not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'hub_actor' AND column_name = 'is_current') THEN
        RAISE EXCEPTION 'hub_actor.is_current was not created';
    END IF;
END $$;

COMMIT;

-- ROLLBACK
--   ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS ck_hub_actor_superseded;
--   ALTER TABLE hub_actor
--       DROP COLUMN IF EXISTS assigned_by, DROP COLUMN IF EXISTS superseded_by,
--       DROP COLUMN IF EXISTS superseded_at, DROP COLUMN IF EXISTS is_current;
--
--   fk_actor_category_type is NOT dropped here. The deferred cutover chain
--   (380, 450, 490) also owns it, and dropping a constraint another migration
--   may legitimately have created would silently weaken the schema. Drop it
--   deliberately if that is really what is wanted.
