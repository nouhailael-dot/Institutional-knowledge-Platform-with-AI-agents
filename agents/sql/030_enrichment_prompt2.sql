-- Prompt 2 enrichment-write fixes. Emit only; do not run automatically.

ALTER TABLE scrape_run
    DROP CONSTRAINT IF EXISTS scrape_run_status_check;

ALTER TABLE scrape_run
    ADD CONSTRAINT scrape_run_status_check
    CHECK (status IN ('running', 'succeeded', 'failed', 'skipped'));

ALTER TABLE field_proposal
    ADD COLUMN IF NOT EXISTS source_id uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'field_proposal_source_id_fkey'
    ) THEN
        ALTER TABLE field_proposal
            ADD CONSTRAINT field_proposal_source_id_fkey
            FOREIGN KEY (source_id) REFERENCES source(source_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_field_proposal_source_id
    ON field_proposal (source_id);
