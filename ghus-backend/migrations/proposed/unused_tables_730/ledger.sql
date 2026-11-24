-- Ledger row for 730. Run right after the migration succeeds. The checksum is the
-- SHA-256 of the committed migration file (LF line endings).

BEGIN;

INSERT INTO public.architecture_v2_migration_ledger (migration_id, source_path, source_sha256)
VALUES ('730', 'migrations/proposed/deferred/730_remove_unused_tables.sql', 'e93be08d14ab9c6c83e67d7bda0eb0d3eeb4b3724c9c5e7da91318e8d48c7872')
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '730' AND source_sha256 = 'e93be08d14ab9c6c83e67d7bda0eb0d3eeb4b3724c9c5e7da91318e8d48c7872') THEN
        RAISE EXCEPTION 'ledger: the 730 row with this checksum is missing';
    END IF;
END $$;

COMMIT;
