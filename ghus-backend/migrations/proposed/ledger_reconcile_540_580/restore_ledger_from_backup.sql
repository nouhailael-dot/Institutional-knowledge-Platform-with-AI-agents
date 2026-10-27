-- LAST RESORT ONLY: make the ledger equal the CSV taken by `export` before the
-- reconciliation. Use only if rollback_reconcile_ledger_540_580.sql cannot be
-- used. The reconciliation only ever inserts, so restoring means deleting the
-- rows that are not in the backup; the script refuses unless, afterwards, the
-- ledger equals the backup exactly (id, path, checksum and applied_at).
--
-- Usage: run_ledger_step.py restore --backup runs/ledger_backup_<stamp>.csv --execute

\set ON_ERROR_STOP on
\if :{?backup_file}
\else
\warn 'restore needs -v backup_file=<ledger_backup_*.csv>'
DO $$ BEGIN RAISE EXCEPTION 'backup_file not given; nothing done'; END $$;
\endif

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = pg_catalog, public;
SET LOCAL application_name = 'ghus_ledger_restore_from_backup';

CREATE TEMP TABLE ledger_backup (
    migration_id text PRIMARY KEY, source_path text NOT NULL,
    source_sha256 text NOT NULL, applied_at timestamptz NOT NULL
) ON COMMIT DROP;
\copy ledger_backup FROM pstdin WITH (FORMAT csv, HEADER)

-- What the restore will remove (rows added after the backup).
SELECT l.* FROM public.architecture_v2_migration_ledger l
WHERE NOT EXISTS (SELECT 1 FROM ledger_backup b WHERE b.migration_id = l.migration_id)
ORDER BY l.migration_id;

DO $$
DECLARE
    missing integer;
    removed integer;
BEGIN
    -- Every backed-up row must still be there unchanged; a restore never re-creates rows.
    SELECT count(*) INTO missing FROM ledger_backup b
    WHERE NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger l
                      WHERE (l.migration_id, l.source_path, l.source_sha256, l.applied_at)
                          = (b.migration_id, b.source_path, b.source_sha256, b.applied_at));
    IF missing > 0 THEN
        RAISE EXCEPTION 'restore refused: % backed-up row(s) are missing or changed; needs a person', missing;
    END IF;
    DELETE FROM public.architecture_v2_migration_ledger l
    WHERE NOT EXISTS (SELECT 1 FROM ledger_backup b WHERE b.migration_id = l.migration_id);
    GET DIAGNOSTICS removed = ROW_COUNT;
    IF (SELECT count(*) FROM public.architecture_v2_migration_ledger) <> (SELECT count(*) FROM ledger_backup) THEN
        RAISE EXCEPTION 'restore failed: ledger does not equal the backup';
    END IF;
    RAISE NOTICE 'restored: % row(s) removed; ledger equals the backup', removed;
END $$;

COMMIT;
