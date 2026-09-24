BEGIN;
DROP POLICY IF EXISTS record_verification_ghus_insert ON record_verification;
DROP POLICY IF EXISTS record_verification_read ON record_verification;
ALTER TABLE record_verification DISABLE ROW LEVEL SECURITY;
DROP TRIGGER IF EXISTS canonical_write_audit_append_only ON canonical_write_audit;
DROP TABLE IF EXISTS canonical_write_audit;
COMMIT;
