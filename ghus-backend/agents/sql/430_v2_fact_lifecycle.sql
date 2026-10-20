-- PROPOSAL ONLY. Supersedes frozen 240 current-fact semantics for Phase 11.
-- ADDITIVE except replacement of views and expansion of review_item kind CHECK.
BEGIN;

ALTER TABLE actor_fact ADD COLUMN IF NOT EXISTS semantic_hash text;
ALTER TABLE actor_fact ADD COLUMN IF NOT EXISTS creator_class text;
ALTER TABLE actor_fact ADD COLUMN IF NOT EXISTS lifecycle_state text;
ALTER TABLE actor_fact ADD COLUMN IF NOT EXISTS supersedes_fact_id uuid REFERENCES actor_fact(actor_fact_id);

ALTER TABLE actor_fact DROP CONSTRAINT IF EXISTS ck_actor_fact_creator_class;
ALTER TABLE actor_fact ADD CONSTRAINT ck_actor_fact_creator_class CHECK (
    creator_class IS NULL OR creator_class IN ('agent','ghus_human')
) NOT VALID;
ALTER TABLE actor_fact DROP CONSTRAINT IF EXISTS ck_actor_fact_lifecycle_state;
ALTER TABLE actor_fact ADD CONSTRAINT ck_actor_fact_lifecycle_state CHECK (
    lifecycle_state IS NULL OR lifecycle_state IN ('accepted','conflict_flagged','pending_update')
) NOT VALID;

CREATE TABLE IF NOT EXISTS actor_fact_current_pointer (
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    topic_id uuid NOT NULL REFERENCES topic(topic_id),
    fact_key text NOT NULL,
    actor_fact_id uuid NOT NULL UNIQUE REFERENCES actor_fact(actor_fact_id),
    changed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id,topic_id,fact_key)
);

CREATE TABLE IF NOT EXISTS fact_corroboration (
    fact_corroboration_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_fact_id uuid NOT NULL REFERENCES actor_fact(actor_fact_id),
    source_id uuid NOT NULL REFERENCES source(source_id),
    request_id uuid,
    confidence text NOT NULL CHECK (confidence IN ('high','medium','low')),
    retrieved_at timestamptz NOT NULL,
    generated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_fact_id,source_id,request_id)
);

-- Existing Phase 3-10 facts predate the pointer. Select one deterministic
-- current row without rewriting any immutable historical fact value.
INSERT INTO actor_fact_current_pointer(actor_id,topic_id,fact_key,actor_fact_id,changed_at)
SELECT actor_id,topic_id,fact_key,actor_fact_id,COALESCE(retrieved_at,created_at,now())
FROM (
    SELECT f.*,row_number() OVER (
        PARTITION BY actor_id,topic_id,fact_key
        ORDER BY retrieved_at DESC NULLS LAST,created_at DESC,actor_fact_id DESC
    ) AS current_rank
    FROM actor_fact f
    WHERE topic_id IS NOT NULL
) ranked
WHERE current_rank=1
ON CONFLICT(actor_id,topic_id,fact_key) DO NOTHING;

CREATE INDEX IF NOT EXISTS ix_actor_fact_semantic
    ON actor_fact(actor_id,topic_id,fact_key,semantic_hash);
CREATE INDEX IF NOT EXISTS ix_fact_corroboration_fact
    ON fact_corroboration(actor_fact_id,created_at);

DROP TRIGGER IF EXISTS fact_corroboration_append_only ON fact_corroboration;
CREATE TRIGGER fact_corroboration_append_only BEFORE UPDATE OR DELETE ON fact_corroboration
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

CREATE OR REPLACE VIEW actor_fact_current_v2 AS
SELECT f.*, TRUE AS is_current
FROM actor_fact_current_pointer p
JOIN actor_fact f ON f.actor_fact_id=p.actor_fact_id;

CREATE OR REPLACE VIEW actor_fact_history AS
SELECT f.*, (p.actor_fact_id IS NOT NULL) AS is_current
FROM actor_fact f
LEFT JOIN actor_fact_current_pointer p ON p.actor_fact_id=f.actor_fact_id;

ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'possible_duplicate','verify_actor','category_doubt','classification',
    'geocode_failed','geocode','hub_needs_review','hub_assignment',
    'hub_radius_overlap','same_topic_overlap','hub_member_outside_radius',
    'hub_center_drift','hub_proposal','new_hub','fact_conflict','pending_update',
    'pending_human_update','identity','affiliation_change'
)) NOT VALID;

COMMIT;
