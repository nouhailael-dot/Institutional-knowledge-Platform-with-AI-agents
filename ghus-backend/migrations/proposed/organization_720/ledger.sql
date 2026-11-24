-- Ledger row for 720. Run right after the migration succeeds. The checksum is the
-- SHA-256 of the committed migration file (LF line endings).

BEGIN;

INSERT INTO public.architecture_v2_migration_ledger (migration_id, source_path, source_sha256)
VALUES ('720', 'migrations/proposed/deferred/720_organization_names.sql', '869f0ec2158b5b5463121cd9eedddb840fe106a70db8a7042d7ca69a11bb3242')
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '720' AND source_sha256 = '869f0ec2158b5b5463121cd9eedddb840fe106a70db8a7042d7ca69a11bb3242') THEN
        RAISE EXCEPTION 'ledger: the 720 row with this checksum is missing';
    END IF;
END $$;

COMMIT;
