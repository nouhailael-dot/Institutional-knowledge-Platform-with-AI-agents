-- Additive split: new audit table and permissions on the new verification table only.
BEGIN;
CREATE TABLE IF NOT EXISTS canonical_write_audit (
    canonical_write_audit_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    writer_module text NOT NULL CHECK (writer_module IN (
        'agents.discovery.promote','agents.enrichment.decisions'
    )),
    operation text NOT NULL CHECK (operation IN (
        'create_actor','append_fact','append_edge','append_verification','create_review_item'
    )),
    entity_type text NOT NULL,
    entity_id uuid,
    collection_run_id uuid REFERENCES collection_run(collection_run_id),
    dry_run boolean NOT NULL DEFAULT true,
    actor_fact_id uuid REFERENCES actor_fact(actor_fact_id),
    entity_edge_id uuid REFERENCES entity_edge(entity_edge_id),
    source_id uuid REFERENCES source(source_id),
    payload_hash text NOT NULL,
    performed_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (dry_run OR source_id IS NOT NULL)
);
DROP TRIGGER IF EXISTS canonical_write_audit_append_only ON canonical_write_audit;
CREATE TRIGGER canonical_write_audit_append_only
BEFORE UPDATE OR DELETE ON canonical_write_audit
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
CREATE INDEX IF NOT EXISTS ix_canonical_write_audit_entity
    ON canonical_write_audit(entity_type,entity_id,created_at DESC);

ALTER TABLE record_verification ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS record_verification_read ON record_verification;
DROP POLICY IF EXISTS record_verification_ghus_insert ON record_verification;
CREATE POLICY record_verification_read ON record_verification
    FOR SELECT TO authenticated, service_role USING (true);
CREATE POLICY record_verification_ghus_insert ON record_verification
    FOR INSERT TO service_role WITH CHECK (true);
REVOKE ALL ON record_verification FROM anon, authenticated;
GRANT SELECT ON record_verification TO authenticated;
GRANT SELECT, INSERT ON record_verification TO service_role;
REVOKE UPDATE, DELETE ON record_verification FROM service_role;
COMMIT;
