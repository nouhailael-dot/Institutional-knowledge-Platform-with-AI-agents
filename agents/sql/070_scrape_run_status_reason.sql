-- Discovery run attention statuses. Emit only; do not run automatically.

ALTER TABLE scrape_run
    ADD COLUMN IF NOT EXISTS status_reason text;

ALTER TABLE scrape_run
    DROP CONSTRAINT IF EXISTS scrape_run_status_check;

ALTER TABLE scrape_run
    ADD CONSTRAINT scrape_run_status_check
    CHECK (status IN ('running', 'succeeded', 'attention', 'failed', 'skipped'));
