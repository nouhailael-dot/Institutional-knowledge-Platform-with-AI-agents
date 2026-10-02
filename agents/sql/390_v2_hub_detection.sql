-- PROPOSAL ONLY. Add Phase 7 evidence without changing legacy hub/proposal behavior.
BEGIN;
CREATE TABLE IF NOT EXISTS hub_detection_run (
    hub_detection_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dry_run boolean NOT NULL DEFAULT true,
    trigger_statuses jsonb NOT NULL,
    method_version text NOT NULL,
    config_snapshot jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('running','completed','failed')),
    eligible_actor_count integer NOT NULL DEFAULT 0 CHECK (eligible_actor_count >= 0),
    proposal_count integer NOT NULL DEFAULT 0 CHECK (proposal_count >= 0),
    suppression_count integer NOT NULL DEFAULT 0 CHECK (suppression_count >= 0),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

ALTER TABLE proposed_hub
    ADD COLUMN IF NOT EXISTS detection_run_id uuid,
    ADD COLUMN IF NOT EXISTS independence_statement text,
    ADD COLUMN IF NOT EXISTS detection_method_version text,
    ADD COLUMN IF NOT EXISTS fingerprint_version text,
    ADD COLUMN IF NOT EXISTS proposal_evidence jsonb,
    ADD COLUMN IF NOT EXISTS trigger_statuses jsonb,
    ADD COLUMN IF NOT EXISTS minimum_families_required integer,
    ADD COLUMN IF NOT EXISTS minimum_categories_required integer;
ALTER TABLE proposed_hub DROP CONSTRAINT IF EXISTS fk_proposed_hub_detection_run;
ALTER TABLE proposed_hub ADD CONSTRAINT fk_proposed_hub_detection_run
    FOREIGN KEY (detection_run_id) REFERENCES hub_detection_run(hub_detection_run_id) NOT VALID;
CREATE INDEX IF NOT EXISTS ix_proposed_hub_detection_run
    ON proposed_hub(detection_run_id) WHERE detection_run_id IS NOT NULL;

ALTER TABLE proposed_hub_member
    ADD COLUMN IF NOT EXISTS category_type text,
    ADD COLUMN IF NOT EXISTS distance_miles_raw double precision,
    ADD COLUMN IF NOT EXISTS matched_category text;
COMMIT;
