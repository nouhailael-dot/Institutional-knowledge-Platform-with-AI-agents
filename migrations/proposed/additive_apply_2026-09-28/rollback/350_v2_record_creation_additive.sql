BEGIN;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM actor
        WHERE source_origin IN ('imported_phase1','claude_discovered','ghus_uploaded_doc')
    ) THEN
        RAISE EXCEPTION 'refusing rollback: Phase 3 source origins are in use';
    END IF;
END $$;
DELETE FROM source_origin_definition
WHERE origin_code IN ('imported_phase1','claude_discovered','ghus_uploaded_doc');
COMMIT;
