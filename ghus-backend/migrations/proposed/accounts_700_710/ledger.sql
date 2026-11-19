-- Ledger rows for 700 and 710. Run right after both migrations succeed, in the same
-- SQL editor session. The checksums are SHA-256 of the committed files (LF line
-- endings, pinned by .gitattributes); tests/db/test_accounts_migration_package.py
-- fails if a file changes without its checksum here.

BEGIN;

INSERT INTO public.architecture_v2_migration_ledger (migration_id, source_path, source_sha256)
VALUES
    ('700', 'migrations/proposed/deferred/700_compass_accounts.sql',
     '8197dc81cf70ea68f92e230558e491cd30f7c27b8d4fc2c06662d08f75cd578e'),
    ('710', 'migrations/proposed/deferred/710_record_deletion_retention.sql',
     'd947eb4b498eb3a965355ba4da45c851f7cebaf15044f140a09f1d2b1a3fefa8')
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF (SELECT count(*) FROM public.architecture_v2_migration_ledger
         WHERE (migration_id, source_sha256) IN (
             ('700', '8197dc81cf70ea68f92e230558e491cd30f7c27b8d4fc2c06662d08f75cd578e'),
             ('710', 'd947eb4b498eb3a965355ba4da45c851f7cebaf15044f140a09f1d2b1a3fefa8'))) <> 2 THEN
        RAISE EXCEPTION 'ledger: two rows with these checksums expected';
    END IF;
END $$;

COMMIT;
