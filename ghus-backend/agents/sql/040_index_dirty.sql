-- Temporary index refresh dirty marker for agent-owned writes.
-- Do not run automatically; this file is emitted for a human migration step.

CREATE TABLE IF NOT EXISTS index_dirty (
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    marked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_type, entity_id)
);
