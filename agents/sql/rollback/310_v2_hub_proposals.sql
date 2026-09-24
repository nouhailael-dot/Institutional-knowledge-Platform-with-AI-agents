BEGIN;
DROP TRIGGER IF EXISTS proposed_hub_decision_append_only ON proposed_hub_decision;
DROP TABLE IF EXISTS proposed_hub_decision;
DROP TABLE IF EXISTS proposed_hub_member;
DROP INDEX IF EXISTS uq_proposed_hub_topic_fingerprint;
ALTER TABLE proposed_hub
    DROP CONSTRAINT IF EXISTS ck_proposed_hub_counts,
    DROP CONSTRAINT IF EXISTS ck_proposed_hub_core,
    DROP CONSTRAINT IF EXISTS ck_proposed_hub_radius,
    DROP CONSTRAINT IF EXISTS ck_proposed_hub_kind,
    DROP CONSTRAINT IF EXISTS fk_proposed_hub_final_hub,
    DROP CONSTRAINT IF EXISTS fk_proposed_hub_topic,
    DROP COLUMN IF EXISTS final_hub_id,
    DROP COLUMN IF EXISTS membership_fingerprint,
    DROP COLUMN IF EXISTS category_count,
    DROP COLUMN IF EXISTS independent_family_count,
    DROP COLUMN IF EXISTS core_radius_miles,
    DROP COLUMN IF EXISTS radius_miles,
    DROP COLUMN IF EXISTS center_longitude,
    DROP COLUMN IF EXISTS center_latitude,
    DROP COLUMN IF EXISTS topic_id,
    DROP COLUMN IF EXISTS proposal_kind;
COMMIT;
