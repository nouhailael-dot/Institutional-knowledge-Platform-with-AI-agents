-- Applied by hand on 2026-09-13 after the column was added to the INSERT
-- without a migration. Recorded here so the sequence is complete.
ALTER TABLE search_candidate ADD COLUMN IF NOT EXISTS duplicate_of uuid;
