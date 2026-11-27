-- Ledger row for 820. Run right after the migration succeeds. The checksum is the
-- SHA-256 of the committed migration file (LF line endings).

BEGIN;

INSERT INTO public.architecture_v2_migration_ledger (migration_id, source_path, source_sha256)
VALUES ('820', 'migrations/proposed/deferred/820_topic_into_sector_and_cleanup.sql', 'ee52cf07bda96dd38b8a2af237a9861f1246099ce36b2879a85b476899e44e6a')
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '820' AND source_sha256 = 'ee52cf07bda96dd38b8a2af237a9861f1246099ce36b2879a85b476899e44e6a') THEN
        RAISE EXCEPTION 'ledger: the 820 row with this checksum is missing';
    END IF;
END $$;

COMMIT;
