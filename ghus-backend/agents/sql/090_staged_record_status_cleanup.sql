-- Keep sector_match as the authoritative out-of-sector classification.
-- status is a lifecycle state and should not duplicate sector handoff state.
UPDATE staged_record
SET status = 'staged',
    updated_at = now()
WHERE sector_match = 'out_of_sector'
  AND status = 'out_of_sector';
