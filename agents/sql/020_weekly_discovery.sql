-- Phase 2 replay/change-detection support. Emit only; do not run automatically.

ALTER TABLE raw_document
    ADD COLUMN IF NOT EXISTS storage_path text;

CREATE INDEX IF NOT EXISTS ix_raw_document_url_content_hash
    ON raw_document (url, content_hash);
