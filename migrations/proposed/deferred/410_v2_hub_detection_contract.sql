-- DEFERRED / BREAKING. Schema-owner execution only after Phase 7 code is deployed.
-- Replaces frozen 310's fixed detector contract with the configuration-backed contract.
BEGIN;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS proposed_hub_status_check;
UPDATE proposed_hub
SET status = CASE status WHEN 'pending' THEN 'open' WHEN 'accepted' THEN 'approved' ELSE status END,
    proposal_evidence = COALESCE(proposal_evidence,'{}'::jsonb)
        || '{"status_contract":"canonical_v2"}'::jsonb
WHERE proposal_kind='deterministic_cluster'
  AND detection_run_id IS NOT NULL
  AND status IN ('pending','accepted','rejected');
ALTER TABLE proposed_hub ADD CONSTRAINT proposed_hub_status_check CHECK (
    (proposal_kind='deterministic_cluster' AND detection_run_id IS NOT NULL
        AND status IN ('open','approved','renamed','rejected'))
    OR
    ((proposal_kind<>'deterministic_cluster' OR detection_run_id IS NULL)
        AND status IN ('pending','accepted','rejected'))
) NOT VALID;

ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS ck_proposed_hub_counts;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_counts CHECK (
    proposal_kind <> 'deterministic_cluster'
    OR (
        independent_family_count >= minimum_families_required
        AND category_count >= minimum_categories_required
        AND minimum_families_required > 0
        AND minimum_categories_required > 0
        AND topic_id IS NOT NULL
        AND membership_fingerprint IS NOT NULL
        AND nullif(btrim(independence_statement),'') IS NOT NULL
        AND nullif(btrim(detection_method_version),'') IS NOT NULL
        AND nullif(btrim(fingerprint_version),'') IS NOT NULL
        AND detection_run_id IS NOT NULL
        AND jsonb_typeof(trigger_statuses) = 'array'
        AND jsonb_array_length(trigger_statuses) > 0
    )
) NOT VALID;

ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS ck_proposed_hub_core;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_core CHECK (
    core_radius_miles IS NULL OR (
        core_radius_miles > 0
        AND radius_miles IS NOT NULL
        AND core_radius_miles <= radius_miles
    )
) NOT VALID;

ALTER TABLE proposed_hub_member ADD CONSTRAINT ck_proposed_hub_member_phase7_evidence CHECK (
    category_type IS NOT NULL
    AND distance_miles_raw IS NOT NULL
    AND distance_miles_raw >= 0
) NOT VALID;
COMMIT;
