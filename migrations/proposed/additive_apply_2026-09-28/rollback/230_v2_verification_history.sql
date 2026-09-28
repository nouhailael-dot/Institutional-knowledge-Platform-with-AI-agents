BEGIN;
DROP TRIGGER IF EXISTS record_verification_append_only ON record_verification;
DROP TABLE IF EXISTS record_verification;
DROP FUNCTION IF EXISTS ghus_reject_mutation();
COMMIT;
