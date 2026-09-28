-- PROPOSAL ONLY. Phase 3 record-creation queue and source-origin corrections.
BEGIN;

INSERT INTO source_origin_definition(origin_code,display_name,description) VALUES
('imported_phase1','Imported','Imported from the Phase 1 production baseline'),
('claude_discovered','Parked','Discovered by the Claude-assisted mapping pipeline'),
('ghus_uploaded_doc','GHUS uploaded document','Created from a GHUS-supplied document')
ON CONFLICT (origin_code) DO NOTHING;

ALTER TABLE review_item
    DROP CONSTRAINT IF EXISTS review_item_review_kind_check;
ALTER TABLE review_item
    DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','fact_conflict','pending_human_update','classification',
    'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub',
    'verify_actor'
)) NOT VALID;

COMMIT;
-- ROLLBACK: 350_v2_record_creation.sql in agents/sql/rollback.
