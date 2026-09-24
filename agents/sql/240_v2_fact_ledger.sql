-- PROPOSAL ONLY. Immutable actor facts plus append-only resolution events.
BEGIN;

CREATE TABLE IF NOT EXISTS actor_fact (
    actor_fact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    topic_id uuid REFERENCES topic(topic_id),
    fact_type text NOT NULL,
    fact_key text NOT NULL,
    fact_value jsonb,
    collection_state text NOT NULL DEFAULT 'found' CHECK (
        collection_state IN ('found','not_found','not_yet_collected')
    ),
    layer smallint NOT NULL CHECK (layer IN (1,2,3)),
    source_id uuid NOT NULL REFERENCES source(source_id),
    source_origin text NOT NULL REFERENCES source_origin_definition(origin_code),
    confidence text NOT NULL CHECK (confidence IN ('high','medium','low')),
    observed_at timestamptz,
    retrieved_at timestamptz NOT NULL,
    generated_by text NOT NULL,
    request_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (collection_state = 'found' AND fact_value IS NOT NULL)
        OR (collection_state <> 'found' AND fact_value IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS fact_resolution (
    fact_resolution_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_fact_id uuid NOT NULL REFERENCES actor_fact(actor_fact_id),
    resolution text NOT NULL CHECK (resolution IN (
        'accepted','superseded','conflict','rejected','pending_human_update'
    )),
    related_actor_fact_id uuid REFERENCES actor_fact(actor_fact_id),
    decided_by text NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (related_actor_fact_id IS NULL OR related_actor_fact_id <> actor_fact_id)
);

CREATE INDEX IF NOT EXISTS ix_actor_fact_lookup
    ON actor_fact(actor_id,topic_id,fact_type,fact_key,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_fact_resolution_fact
    ON fact_resolution(actor_fact_id,created_at DESC);

DROP TRIGGER IF EXISTS actor_fact_append_only ON actor_fact;
CREATE TRIGGER actor_fact_append_only BEFORE UPDATE OR DELETE ON actor_fact
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
DROP TRIGGER IF EXISTS fact_resolution_append_only ON fact_resolution;
CREATE TRIGGER fact_resolution_append_only BEFORE UPDATE OR DELETE ON fact_resolution
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

CREATE OR REPLACE VIEW actor_fact_current AS
WITH latest_resolution AS (
    SELECT DISTINCT ON (actor_fact_id)
        actor_fact_id, resolution, related_actor_fact_id, created_at
    FROM fact_resolution
    ORDER BY actor_fact_id, created_at DESC, fact_resolution_id DESC
)
SELECT f.*, COALESCE(r.resolution,'accepted') AS resolution_state
FROM actor_fact f
LEFT JOIN latest_resolution r USING (actor_fact_id)
WHERE COALESCE(r.resolution,'accepted') IN ('accepted','pending_human_update','conflict');

COMMIT;
-- ROLLBACK: export both ledgers, drop view/triggers/tables in dependency order.
