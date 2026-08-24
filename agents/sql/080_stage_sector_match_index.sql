-- Make sector_match the authoritative teammate handoff filter.
-- Emit only; do not run automatically.

UPDATE staged_record
SET sector_match = 'out_of_sector'
WHERE status = 'out_of_sector'
  AND sector_match <> 'out_of_sector';

DROP INDEX IF EXISTS idx_staged_record_out_of_sector;

CREATE INDEX IF NOT EXISTS idx_staged_record_out_of_sector
    ON staged_record (run_id, entity_type, updated_at)
    WHERE sector_match = 'out_of_sector';
