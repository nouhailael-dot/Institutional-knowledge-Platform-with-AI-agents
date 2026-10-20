-- PROPOSAL ONLY. Extend the existing review-admission proposal root in place.
BEGIN;
ALTER TABLE proposed_hub
    ADD COLUMN IF NOT EXISTS proposal_kind text NOT NULL DEFAULT 'legacy_review',
    ADD COLUMN IF NOT EXISTS topic_id uuid,
    ADD COLUMN IF NOT EXISTS center_latitude numeric(9,6),
    ADD COLUMN IF NOT EXISTS center_longitude numeric(9,6),
    ADD COLUMN IF NOT EXISTS radius_miles numeric(7,2),
    ADD COLUMN IF NOT EXISTS core_radius_miles numeric(7,2),
    ADD COLUMN IF NOT EXISTS independent_family_count integer,
    ADD COLUMN IF NOT EXISTS category_count integer,
    ADD COLUMN IF NOT EXISTS membership_fingerprint text,
    ADD COLUMN IF NOT EXISTS final_hub_id uuid;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS fk_proposed_hub_topic;
ALTER TABLE proposed_hub ADD CONSTRAINT fk_proposed_hub_topic
    FOREIGN KEY (topic_id) REFERENCES topic(topic_id) NOT VALID;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS fk_proposed_hub_final_hub;
ALTER TABLE proposed_hub ADD CONSTRAINT fk_proposed_hub_final_hub
    FOREIGN KEY (final_hub_id) REFERENCES hub(hub_id) NOT VALID;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS ck_proposed_hub_kind;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_kind
    CHECK (proposal_kind IN ('legacy_review','deterministic_cluster')) NOT VALID;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS ck_proposed_hub_radius;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_radius
    CHECK (radius_miles IS NULL OR (radius_miles > 0 AND radius_miles <= 200)) NOT VALID;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS ck_proposed_hub_core;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_core
    CHECK (core_radius_miles IS NULL OR core_radius_miles = 50) NOT VALID;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS ck_proposed_hub_counts;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_counts CHECK (
    proposal_kind <> 'deterministic_cluster'
    OR (independent_family_count >= 10 AND category_count >= 5
        AND topic_id IS NOT NULL AND membership_fingerprint IS NOT NULL)
) NOT VALID;
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
