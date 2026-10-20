BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM hub_detection_run)
       OR EXISTS (SELECT 1 FROM proposed_hub WHERE detection_run_id IS NOT NULL)
    THEN
        RAISE EXCEPTION 'export/remove Phase 7 hub detection evidence before rollback';
    END IF;
END $$;
ALTER TABLE proposed_hub_member
    DROP COLUMN IF EXISTS matched_category,
    DROP COLUMN IF EXISTS distance_miles_raw,
    DROP COLUMN IF EXISTS category_type;
DROP INDEX IF EXISTS ix_proposed_hub_detection_run;
ALTER TABLE proposed_hub
    DROP CONSTRAINT IF EXISTS fk_proposed_hub_detection_run,
    DROP COLUMN IF EXISTS minimum_categories_required,
    DROP COLUMN IF EXISTS minimum_families_required,
    DROP COLUMN IF EXISTS trigger_statuses,
    DROP COLUMN IF EXISTS proposal_evidence,
    DROP COLUMN IF EXISTS fingerprint_version,
    DROP COLUMN IF EXISTS detection_method_version,
    DROP COLUMN IF EXISTS independence_statement,
    DROP COLUMN IF EXISTS detection_run_id;
DROP TABLE IF EXISTS hub_detection_run;
COMMIT;
