-- Rollback 730: removes the organization_template view. No data is touched.
-- Then: DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '730';

BEGIN;
SET LOCAL lock_timeout = '15s';
DROP VIEW public.organization_template;
COMMIT;
