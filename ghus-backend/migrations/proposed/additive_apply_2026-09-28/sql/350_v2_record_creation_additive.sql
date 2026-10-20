-- Additive split of agents/sql/350_v2_record_creation.sql.
-- The existing review_item CHECK replacement that adds verify_actor is deferred.
BEGIN;
INSERT INTO source_origin_definition(origin_code,display_name,description) VALUES
('imported_phase1','Imported','Imported from the Phase 1 production baseline'),
('claude_discovered','Parked','Discovered by the Claude-assisted mapping pipeline'),
('ghus_uploaded_doc','GHUS uploaded document','Created from a GHUS-supplied document')
ON CONFLICT (origin_code) DO NOTHING;
COMMIT;
