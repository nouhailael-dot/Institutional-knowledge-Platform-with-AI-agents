-- Isolated rollback. Export lifecycle rows before use outside a disposable test DB.
BEGIN;
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','fact_conflict','pending_human_update','classification',
    'geocode','hub_assignment','same_topic_overlap','hub_center_drift','new_hub',
    'verify_actor','category_doubt','hub_needs_review','hub_radius_overlap',
    'hub_member_outside_radius'
)) NOT VALID;
DROP VIEW IF EXISTS actor_fact_history;
DROP VIEW IF EXISTS actor_fact_current_v2;
DROP TRIGGER IF EXISTS fact_corroboration_append_only ON fact_corroboration;
DROP TABLE IF EXISTS fact_corroboration;
DROP TABLE IF EXISTS actor_fact_current_pointer;
DROP INDEX IF EXISTS ix_actor_fact_semantic;
ALTER TABLE actor_fact DROP COLUMN IF EXISTS supersedes_fact_id;
ALTER TABLE actor_fact DROP COLUMN IF EXISTS lifecycle_state;
ALTER TABLE actor_fact DROP COLUMN IF EXISTS creator_class;
ALTER TABLE actor_fact DROP COLUMN IF EXISTS semantic_hash;
COMMIT;
