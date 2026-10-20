-- Additive split of agents/sql/310_v2_hub_proposals.sql.
-- The root-table default, NOT NULL, FKs, and CHECK constraints are deferred.
BEGIN;
ALTER TABLE proposed_hub
    ADD COLUMN IF NOT EXISTS proposal_kind text,
    ADD COLUMN IF NOT EXISTS topic_id uuid,
    ADD COLUMN IF NOT EXISTS center_latitude numeric(9,6),
    ADD COLUMN IF NOT EXISTS center_longitude numeric(9,6),
    ADD COLUMN IF NOT EXISTS radius_miles numeric(7,2),
    ADD COLUMN IF NOT EXISTS core_radius_miles numeric(7,2),
    ADD COLUMN IF NOT EXISTS independent_family_count integer,
    ADD COLUMN IF NOT EXISTS category_count integer,
    ADD COLUMN IF NOT EXISTS membership_fingerprint text,
    ADD COLUMN IF NOT EXISTS final_hub_id uuid;
CREATE UNIQUE INDEX IF NOT EXISTS uq_proposed_hub_topic_fingerprint
    ON proposed_hub(topic_id,membership_fingerprint)
    WHERE membership_fingerprint IS NOT NULL;

CREATE TABLE IF NOT EXISTS proposed_hub_member (
    proposed_hub_id uuid NOT NULL REFERENCES proposed_hub(proposed_hub_id),
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    family_root_actor_id uuid NOT NULL REFERENCES actor(actor_id),
    distance_miles numeric(8,2) NOT NULL CHECK (distance_miles <= 200),
    actor_category text NOT NULL,
    PRIMARY KEY (proposed_hub_id,actor_id)
);
CREATE TABLE IF NOT EXISTS proposed_hub_decision (
    proposed_hub_decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proposed_hub_id uuid NOT NULL REFERENCES proposed_hub(proposed_hub_id),
    decision text NOT NULL CHECK (decision IN ('approve','rename','reject','set_radius')),
    final_name text,
    final_radius_miles numeric(7,2) CHECK (final_radius_miles > 0 AND final_radius_miles <= 200),
    decided_by text NOT NULL,
    notes text,
    decided_at timestamptz NOT NULL DEFAULT now(),
    CHECK (decision <> 'rename' OR nullif(btrim(final_name),'') IS NOT NULL),
    CHECK (decision <> 'set_radius' OR final_radius_miles IS NOT NULL)
);
DROP TRIGGER IF EXISTS proposed_hub_decision_append_only ON proposed_hub_decision;
CREATE TRIGGER proposed_hub_decision_append_only
BEFORE UPDATE OR DELETE ON proposed_hub_decision
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
COMMIT;
