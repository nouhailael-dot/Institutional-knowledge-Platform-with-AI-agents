-- Ledger row for 750. Run right after the migration succeeds. The checksum is the
-- SHA-256 of the committed migration file (LF line endings).

BEGIN;

INSERT INTO public.architecture_v2_migration_ledger (migration_id, source_path, source_sha256)
VALUES ('750', 'migrations/proposed/deferred/750_remove_unused_tables.sql', '6af4e59fdbc92c90afa22d5a4b42719caadb773803c27c74057b69e7f042f32f')
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '750' AND source_sha256 = '6af4e59fdbc92c90afa22d5a4b42719caadb773803c27c74057b69e7f042f32f') THEN
        RAISE EXCEPTION 'ledger: the 750 row with this checksum is missing';
    END IF;
END $$;

COMMIT;
