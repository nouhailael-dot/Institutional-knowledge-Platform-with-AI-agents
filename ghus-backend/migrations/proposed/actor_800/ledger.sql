-- Ledger row for 800. Run right after the migration succeeds. The checksum is the
-- SHA-256 of the committed migration file (LF line endings).

BEGIN;

INSERT INTO public.architecture_v2_migration_ledger (migration_id, source_path, source_sha256)
VALUES ('800', 'migrations/proposed/deferred/800_actor_names.sql', '829d46a5f25c5cf0168ede3dab5fda876f10caed5c3e17e8848239cceeab0e55')
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '800' AND source_sha256 = '829d46a5f25c5cf0168ede3dab5fda876f10caed5c3e17e8848239cceeab0e55') THEN
        RAISE EXCEPTION 'ledger: the 800 row with this checksum is missing';
    END IF;
END $$;

COMMIT;
