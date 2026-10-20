-- PROPOSAL ONLY. Exact rollback for Phase 8's superseding contract.
BEGIN;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM entity_edge WHERE relationship_type='connected_to_um6p_ocp'
    ) THEN
        RAISE EXCEPTION 'rollback refuses canonical connected_to_um6p_ocp rows; export/resolve first';
    END IF;
END $$;
DROP VIEW IF EXISTS actor_descendants;
DROP TRIGGER IF EXISTS entity_edge_prevent_family_cycle ON entity_edge;
DROP TRIGGER IF EXISTS entity_edge_validate ON entity_edge;
DROP FUNCTION IF EXISTS ghus_prevent_actor_family_cycle();
DROP FUNCTION IF EXISTS ghus_validate_entity_edge();
DROP INDEX IF EXISTS uq_entity_edge_identity;
ALTER TABLE entity_edge DROP CONSTRAINT IF EXISTS entity_edge_relationship_type_check;
ALTER TABLE entity_edge ADD CONSTRAINT entity_edge_relationship_type_check CHECK (
    relationship_type IN (
        'unit_of','operated_by','affiliated_with','member_of','portfolio_of',
        'spinout_of','funded_by','collaborates_with','organizes','participates_in',
        'connected_to_strategic_entity'
    )
);
DROP TABLE IF EXISTS entity_edge_type_definition;
COMMIT;
