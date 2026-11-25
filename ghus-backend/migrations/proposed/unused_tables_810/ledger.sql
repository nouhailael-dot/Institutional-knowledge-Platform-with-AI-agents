-- Ledger row for 810. Run right after the migration succeeds. The checksum is the
-- SHA-256 of the committed migration file (LF line endings).

BEGIN;

INSERT INTO public.architecture_v2_migration_ledger (migration_id, source_path, source_sha256)
VALUES ('810', 'migrations/proposed/deferred/810_remove_unused_tables.sql', '372d76107f0a2cdf99165725e3df3920118b819e5577273d9c419e4ee575d4d9')
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '810' AND source_sha256 = '372d76107f0a2cdf99165725e3df3920118b819e5577273d9c419e4ee575d4d9') THEN
        RAISE EXCEPTION 'ledger: the 810 row with this checksum is missing';
    END IF;
END $$;

COMMIT;
