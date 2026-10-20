BEGIN;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM proposed_hub
        WHERE detection_run_id IS NOT NULL
          AND status='renamed'
          AND proposal_evidence->>'status_contract'='canonical_v2'
    ) THEN
        RAISE EXCEPTION 'export/resolve renamed Phase 7 proposals before contract rollback';
    END IF;
    IF EXISTS (
        SELECT 1 FROM proposed_hub
        WHERE detection_run_id IS NOT NULL
          AND (
              independent_family_count < 10
              OR category_count < 5
              OR core_radius_miles IS DISTINCT FROM 50
              OR radius_miles > 200
          )
    ) THEN
        RAISE EXCEPTION 'Phase 7 rows are incompatible with the frozen proposal 310 contract';
    END IF;
END $$;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS proposed_hub_status_check;
UPDATE proposed_hub
SET status = CASE
        WHEN status='open' THEN 'pending'
        WHEN status IN ('approved','renamed') THEN 'accepted'
        ELSE status
    END,
    proposal_evidence = proposal_evidence - 'status_contract'
WHERE proposal_kind='deterministic_cluster'
  AND detection_run_id IS NOT NULL
  AND proposal_evidence->>'status_contract'='canonical_v2';
ALTER TABLE proposed_hub ADD CONSTRAINT proposed_hub_status_check
    CHECK (status IN ('pending','accepted','rejected')) NOT VALID;
ALTER TABLE proposed_hub_member
    DROP CONSTRAINT IF EXISTS ck_proposed_hub_member_phase7_evidence;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS ck_proposed_hub_core;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_core
    CHECK (core_radius_miles IS NULL OR core_radius_miles = 50) NOT VALID;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS ck_proposed_hub_counts;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_counts CHECK (
    proposal_kind <> 'deterministic_cluster'
    OR (independent_family_count >= 10 AND category_count >= 5
        AND topic_id IS NOT NULL AND membership_fingerprint IS NOT NULL)
) NOT VALID;
COMMIT;
