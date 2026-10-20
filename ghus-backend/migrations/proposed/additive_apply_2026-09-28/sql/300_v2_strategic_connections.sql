-- PROPOSAL ONLY. UM6P/OCP/INNOVX allowlist and three-state checks.
BEGIN;

CREATE TABLE IF NOT EXISTS strategic_entity (
    strategic_entity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name text NOT NULL UNIQUE,
    alternate_names text[] NOT NULL DEFAULT '{}',
    parent_strategic_entity_id uuid REFERENCES strategic_entity(strategic_entity_id),
    entity_group text NOT NULL CHECK (entity_group IN ('OCP','UM6P','INNOVX')),
    source_id uuid NOT NULL REFERENCES source(source_id),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actor_strategic_connection_check (
    connection_check_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    topic_id uuid REFERENCES topic(topic_id),
    layer smallint NOT NULL CHECK (layer IN (1,2,3)),
    state text NOT NULL CHECK (state IN ('found','not_found_so_far','not_yet_checked')),
    strategic_entity_id uuid REFERENCES strategic_entity(strategic_entity_id),
    connection_kind text,
    source_id uuid REFERENCES source(source_id),
    fetched_document_ids uuid[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (state='found' AND strategic_entity_id IS NOT NULL AND source_id IS NOT NULL
             AND nullif(btrim(connection_kind),'') IS NOT NULL)
        OR (state<>'found' AND strategic_entity_id IS NULL AND connection_kind IS NULL)
    )
);

DROP TRIGGER IF EXISTS actor_strategic_connection_check_append_only
    ON actor_strategic_connection_check;
CREATE TRIGGER actor_strategic_connection_check_append_only
BEFORE UPDATE OR DELETE ON actor_strategic_connection_check
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
COMMIT;
-- ROLLBACK: export checks/allowlist, drop both tables.
