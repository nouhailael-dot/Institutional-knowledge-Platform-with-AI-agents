-- PROPOSAL ONLY. GHUS Phase 12 policy correction; isolated proof first.
-- Supersedes the verification/category assumptions in 450/460 without editing
-- either historical proposal.
BEGIN;

CREATE OR REPLACE FUNCTION ghus_phase12_legacy_category(legacy_value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE lower(btrim(legacy_value))
    WHEN 'university' THEN 'university_academic'
    WHEN 'university_academic' THEN 'university_academic'
    WHEN 'university_lab' THEN 'research_center'
    WHEN 'research_organization' THEN 'research_center'
    WHEN 'national_research_center' THEN 'research_center'
    WHEN 'research_center' THEN 'research_center'
    WHEN 'national_research_lab' THEN 'national_laboratory'
    WHEN 'federal_research_system' THEN 'national_laboratory'
    WHEN 'national_laboratory' THEN 'national_laboratory'
    WHEN 'applied_facility' THEN 'applied_facility'
    WHEN 'hospital_clinical' THEN 'hospital_clinical'
    WHEN 'company' THEN 'company'
    WHEN 'corporate_rd_lab' THEN 'company'
    WHEN 'industrial_partner' THEN 'company'
    WHEN 'project_developer' THEN 'company'
    WHEN 'startup' THEN 'startup'
    WHEN 'accelerator' THEN 'innovation_platform'
    WHEN 'innovation_platform' THEN 'innovation_platform'
    WHEN 'venture_capital' THEN 'investor'
    WHEN 'investor' THEN 'investor'
    WHEN 'government' THEN 'government'
    WHEN 'government agency' THEN 'government'
    WHEN 'government_agency' THEN 'government'
    WHEN 'federal_agency' THEN 'government'
    WHEN 'state_agency' THEN 'government'
    WHEN 'foundation_nonprofit' THEN 'foundation_nonprofit'
    WHEN 'nonprofit' THEN 'foundation_nonprofit'
    WHEN 'association_network' THEN 'association_network'
    WHEN 'consortium' THEN 'association_network'
    WHEN 'industry_association' THEN 'association_network'
    WHEN 'intergovernmental_organization' THEN 'association_network'
    WHEN 'un_agency' THEN 'association_network'
    WHEN 'un_committee' THEN 'association_network'
    WHEN 'un_programme' THEN 'association_network'
    WHEN 'un_secretariat' THEN 'association_network'
    ELSE NULL
  END
$$;

ALTER TABLE actor_verification_event
    ADD COLUMN IF NOT EXISTS decision_origin text NOT NULL DEFAULT 'ghus_review',
    ADD COLUMN IF NOT EXISTS migration_batch_id text,
    ADD COLUMN IF NOT EXISTS recorded_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE actor_verification_event ALTER COLUMN decided_by DROP NOT NULL;
ALTER TABLE actor_verification_event ALTER COLUMN decided_at DROP NOT NULL;
ALTER TABLE actor_verification_event
    DROP CONSTRAINT IF EXISTS actor_verification_event_decided_by_check;
ALTER TABLE actor_verification_event
    DROP CONSTRAINT IF EXISTS ck_actor_verification_event_origin;
ALTER TABLE actor_verification_event ADD CONSTRAINT ck_actor_verification_event_origin CHECK (
    (decision_origin='ghus_review'
      AND nullif(btrim(decided_by),'') IS NOT NULL
      AND decided_at IS NOT NULL
      AND migration_batch_id IS NULL)
    OR
    (decision_origin='existing_canonical_migration'
      AND decision='verified'
      AND decided_by IS NULL
      AND decided_at IS NULL
      AND nullif(btrim(migration_batch_id),'') IS NOT NULL
      AND topic_id IS NULL)
) NOT VALID;
CREATE UNIQUE INDEX IF NOT EXISTS ux_actor_existing_canonical_bootstrap
    ON actor_verification_event(actor_id)
    WHERE decision_origin='existing_canonical_migration';

CREATE TABLE IF NOT EXISTS actor_category_migration_audit (
    actor_id uuid PRIMARY KEY REFERENCES actor(actor_id),
    migration_batch_id text NOT NULL,
    legacy_category text,
    legacy_category_raw text,
    mapped_category text REFERENCES actor_category_definition(category_code),
    mapping_status text NOT NULL CHECK (mapping_status IN ('mapped','requires_review')),
    prior_status text,
    prior_source_origin text,
    prior_category_note text,
    prior_category_needs_review boolean,
    migrated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE actor_category_migration_audit
    ADD COLUMN IF NOT EXISTS legacy_category_raw text;
DROP TRIGGER IF EXISTS actor_category_migration_audit_append_only
    ON actor_category_migration_audit;
CREATE TRIGGER actor_category_migration_audit_append_only
BEFORE UPDATE OR DELETE ON actor_category_migration_audit
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

CREATE TABLE IF NOT EXISTS architecture_v2_cutover_attestation (
    audit_name text PRIMARY KEY,
    artifact_sha256 text NOT NULL,
    passed boolean NOT NULL,
    approved_by text NOT NULL,
    approved_at timestamptz NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE OR REPLACE FUNCTION ghus_guard_actor_status() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status IN ('verified','rejected')
     AND COALESCE(current_setting('ghus.verification_projection',true),'off') <> 'on'
  THEN
    RAISE EXCEPTION 'verified/rejected status requires actor_verification_event';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS actor_status_verification_guard ON actor;
CREATE TRIGGER actor_status_verification_guard
BEFORE INSERT OR UPDATE OF status ON actor
FOR EACH ROW EXECUTE FUNCTION ghus_guard_actor_status();

CREATE OR REPLACE FUNCTION ghus_project_actor_verification_status() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
    PERFORM set_config('ghus.verification_projection','on',true);
    UPDATE actor SET status=NEW.decision,updated_at=now() WHERE actor_id=NEW.actor_id;
    PERFORM set_config('ghus.verification_projection','off',true);
    RETURN NEW;
END;
$$;

DROP POLICY IF EXISTS actor_verification_event_ghus_insert ON actor_verification_event;
CREATE POLICY actor_verification_event_ghus_insert ON actor_verification_event
    FOR INSERT TO service_role
    WITH CHECK (
      decision_origin='ghus_review'
      AND nullif(btrim(decided_by),'') IS NOT NULL
      AND decided_at IS NOT NULL
      AND migration_batch_id IS NULL
    );
REVOKE UPDATE (status) ON actor FROM service_role;

COMMIT;
