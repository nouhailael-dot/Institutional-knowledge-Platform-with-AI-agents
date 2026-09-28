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
    op.execute("""
        UPDATE actor
        SET actor_category = actor_type,
            record_status = verification_status
        WHERE actor_category IS DISTINCT FROM actor_type
           OR record_status IS DISTINCT FROM verification_status
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION ghus_sync_actor_v2_compat() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.actor_type IS NOT NULL AND NEW.actor_category IS NOT NULL
               AND NEW.actor_type IS DISTINCT FROM NEW.actor_category THEN
              RAISE EXCEPTION 'actor_type and actor_category must match during compatibility period';
            END IF;
            NEW.actor_type := COALESCE(NEW.actor_type, NEW.actor_category);
            NEW.actor_category := COALESCE(NEW.actor_category, NEW.actor_type);
            IF NEW.verification_status IS NOT NULL AND NEW.record_status IS NOT NULL
               AND NEW.verification_status IS DISTINCT FROM NEW.record_status THEN
              RAISE EXCEPTION 'verification_status and record_status must match during compatibility period';
            END IF;
            NEW.verification_status := COALESCE(NEW.verification_status, NEW.record_status);
            NEW.record_status := COALESCE(NEW.record_status, NEW.verification_status);
          ELSE
            IF NEW.actor_type IS DISTINCT FROM OLD.actor_type
               AND NEW.actor_category IS NOT DISTINCT FROM OLD.actor_category THEN
              NEW.actor_category := NEW.actor_type;
            ELSIF NEW.actor_category IS DISTINCT FROM OLD.actor_category
               AND NEW.actor_type IS NOT DISTINCT FROM OLD.actor_type THEN
              NEW.actor_type := NEW.actor_category;
            ELSIF NEW.actor_type IS DISTINCT FROM NEW.actor_category THEN
              RAISE EXCEPTION 'actor_type and actor_category changed inconsistently';
            END IF;
            IF NEW.verification_status IS DISTINCT FROM OLD.verification_status
               AND NEW.record_status IS NOT DISTINCT FROM OLD.record_status THEN
              NEW.record_status := NEW.verification_status;
            ELSIF NEW.record_status IS DISTINCT FROM OLD.record_status
               AND NEW.verification_status IS NOT DISTINCT FROM OLD.verification_status THEN
              NEW.verification_status := NEW.record_status;
            ELSIF NEW.verification_status IS DISTINCT FROM NEW.record_status THEN
              RAISE EXCEPTION 'verification_status and record_status changed inconsistently';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("DROP TRIGGER IF EXISTS actor_v2_compat_sync ON actor")
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
            WHERE actor_category IS DISTINCT FROM actor_type
               OR record_status IS DISTINCT FROM verification_status
          ) THEN
            RAISE EXCEPTION 'refusing rollback: V2 compatibility columns diverge from legacy columns';
          END IF;
        END $$
    """)
    op.execute("DROP TRIGGER IF EXISTS actor_v2_compat_sync ON actor")
    op.execute("DROP FUNCTION IF EXISTS ghus_sync_actor_v2_compat()")
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
