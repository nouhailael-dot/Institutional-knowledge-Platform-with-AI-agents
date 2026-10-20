BEGIN;
DROP VIEW IF EXISTS actor_descendant_edge;
DROP TRIGGER IF EXISTS entity_edge_append_only ON entity_edge;
DROP TABLE IF EXISTS entity_edge;
COMMIT;
