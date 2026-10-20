-- PROPOSAL ONLY. Immutable, sourced relationships across record types.
BEGIN;

CREATE TABLE IF NOT EXISTS entity_edge (
    entity_edge_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_type text NOT NULL CHECK (subject_type IN ('actor','person','event','strategic_entity')),
    subject_id uuid NOT NULL,
    relationship_type text NOT NULL CHECK (relationship_type IN (
        'unit_of','operated_by','affiliated_with','member_of','portfolio_of',
        'spinout_of','funded_by','collaborates_with','organizes','participates_in',
        'connected_to_strategic_entity'
    )),
    object_type text NOT NULL CHECK (object_type IN ('actor','person','event','strategic_entity')),
    object_id uuid NOT NULL,
    topic_id uuid REFERENCES topic(topic_id),
    source_id uuid NOT NULL REFERENCES source(source_id),
    confidence text NOT NULL CHECK (confidence IN ('high','medium','low')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (subject_type <> object_type OR subject_id <> object_id),
    UNIQUE (subject_type,subject_id,relationship_type,object_type,object_id,topic_id,source_id)
);

CREATE INDEX IF NOT EXISTS ix_entity_edge_subject ON entity_edge(subject_type,subject_id);
CREATE INDEX IF NOT EXISTS ix_entity_edge_object ON entity_edge(object_type,object_id);
CREATE INDEX IF NOT EXISTS ix_entity_edge_topic ON entity_edge(topic_id);

DROP TRIGGER IF EXISTS entity_edge_append_only ON entity_edge;
CREATE TRIGGER entity_edge_append_only BEFORE UPDATE OR DELETE ON entity_edge
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

CREATE OR REPLACE VIEW actor_descendant_edge AS
WITH RECURSIVE descendants(root_actor_id, descendant_actor_id, depth, path) AS (
    SELECT object_id, subject_id, 1, ARRAY[object_id,subject_id]
    FROM entity_edge
    WHERE subject_type='actor' AND object_type='actor'
      AND relationship_type IN ('unit_of','operated_by')
    UNION ALL
    SELECT d.root_actor_id, e.subject_id, d.depth + 1, d.path || e.subject_id
    FROM descendants d
    JOIN entity_edge e ON e.object_id=d.descendant_actor_id
    WHERE e.subject_type='actor' AND e.object_type='actor'
      AND e.relationship_type IN ('unit_of','operated_by')
      AND NOT e.subject_id = ANY(d.path)
)
SELECT * FROM descendants;

COMMIT;
-- ROLLBACK: export edges, drop view/trigger/table.

