"""Additive half of V2 actor identity: legacy columns remain authoritative."""

from alembic import op

revision = "v2a01_actor_add"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE actor
          ADD COLUMN IF NOT EXISTS actor_category text,
          ADD COLUMN IF NOT EXISTS record_status text,
          ADD COLUMN IF NOT EXISTS alternate_names text[],
          ADD COLUMN IF NOT EXISTS category_type text,
          ADD COLUMN IF NOT EXISTS category_note text,
          ADD COLUMN IF NOT EXISTS category_needs_review boolean,
          ADD COLUMN IF NOT EXISTS website_domain text,
          ADD COLUMN IF NOT EXISTS state_code text,
          ADD COLUMN IF NOT EXISTS region_code text,
          ADD COLUMN IF NOT EXISTS latitude numeric(9,6),
          ADD COLUMN IF NOT EXISTS longitude numeric(9,6),
          ADD COLUMN IF NOT EXISTS is_multi_location boolean,
          ADD COLUMN IF NOT EXISTS source_origin text,
          ADD COLUMN IF NOT EXISTS ghus_notes text
    """)
    op.execute("DROP TRIGGER IF EXISTS actor_v2_compat_sync ON actor")
    op.execute("""
        CREATE OR REPLACE FUNCTION ghus_legacy_actor_category(legacy_type text)
        RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
          SELECT CASE lower(btrim(legacy_type))
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
        $$
    """)
    op.execute("""
        UPDATE actor
        SET actor_category = ghus_legacy_actor_category(actor_type),
            record_status = verification_status
        WHERE actor_category IS DISTINCT FROM ghus_legacy_actor_category(actor_type)
           OR record_status IS DISTINCT FROM verification_status
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION ghus_sync_actor_v2_compat() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.actor_type IS NOT NULL THEN
              NEW.actor_category := ghus_legacy_actor_category(NEW.actor_type);
            ELSIF NEW.actor_category IS NOT NULL THEN
              NEW.actor_type := NEW.actor_category;
            END IF;
            IF NEW.verification_status IS NOT NULL THEN
              NEW.record_status := NEW.verification_status;
            ELSIF NEW.record_status IS NOT NULL THEN
              NEW.verification_status := NEW.record_status;
            END IF;
          ELSE
            IF NEW.actor_type IS DISTINCT FROM OLD.actor_type THEN
              NEW.actor_category := ghus_legacy_actor_category(NEW.actor_type);
            ELSIF NEW.actor_category IS DISTINCT FROM OLD.actor_category THEN
              NEW.actor_type := NEW.actor_category;
            END IF;
            IF NEW.verification_status IS DISTINCT FROM OLD.verification_status THEN
              NEW.record_status := NEW.verification_status;
            ELSIF NEW.record_status IS DISTINCT FROM OLD.record_status THEN
              NEW.verification_status := NEW.record_status;
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER actor_v2_compat_sync
        BEFORE INSERT OR UPDATE OF actor_type,actor_category,verification_status,record_status
        ON actor FOR EACH ROW EXECUTE FUNCTION ghus_sync_actor_v2_compat()
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_actor_website_domain ON actor(lower(website_domain))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_actor_name_normalized ON actor(lower(name))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_actor_alternate_names_gin ON actor USING gin(alternate_names)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_actor_geography ON actor(region_code,state_code,location_city)")


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM actor
            WHERE actor_category IS DISTINCT FROM ghus_legacy_actor_category(actor_type)
               OR record_status IS DISTINCT FROM verification_status
          ) THEN
            RAISE EXCEPTION 'refusing rollback: V2 compatibility columns diverge from legacy columns';
          END IF;
        END $$
    """)
    op.execute("DROP TRIGGER IF EXISTS actor_v2_compat_sync ON actor")
    op.execute("DROP FUNCTION IF EXISTS ghus_sync_actor_v2_compat()")
    op.execute("DROP FUNCTION IF EXISTS ghus_legacy_actor_category(text)")
    for name in (
        "ix_actor_website_domain",
        "ix_actor_name_normalized",
        "ix_actor_alternate_names_gin",
        "ix_actor_geography",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.execute("""
        ALTER TABLE actor
          DROP COLUMN IF EXISTS actor_category,
          DROP COLUMN IF EXISTS record_status,
          DROP COLUMN IF EXISTS alternate_names,
          DROP COLUMN IF EXISTS category_type,
          DROP COLUMN IF EXISTS category_note,
          DROP COLUMN IF EXISTS category_needs_review,
          DROP COLUMN IF EXISTS website_domain,
          DROP COLUMN IF EXISTS state_code,
          DROP COLUMN IF EXISTS region_code,
          DROP COLUMN IF EXISTS latitude,
          DROP COLUMN IF EXISTS longitude,
          DROP COLUMN IF EXISTS is_multi_location,
          DROP COLUMN IF EXISTS source_origin,
          DROP COLUMN IF EXISTS ghus_notes
    """)
