-- Read-only backup of the whole migration ledger, written next to the run logs.
-- Restore (last resort only): \copy architecture_v2_migration_ledger FROM '<file>' CSV HEADER
-- after deleting the rows that are not in the file.

\set ON_ERROR_STOP on
BEGIN READ ONLY;
SELECT count(*) AS ledger_rows, max(applied_at) AS latest FROM architecture_v2_migration_ledger;
COPY (SELECT migration_id, source_path, source_sha256, applied_at
      FROM architecture_v2_migration_ledger ORDER BY migration_id)
  TO STDOUT WITH (FORMAT csv, HEADER) \g :backup_file
ROLLBACK;
\echo 'ledger exported to runs/' :backup_file
