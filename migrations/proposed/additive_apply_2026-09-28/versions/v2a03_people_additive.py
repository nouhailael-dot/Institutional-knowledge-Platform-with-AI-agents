"""Additive half of V2 person identity: no rename and nullable columns only."""

from alembic import op

revision = "v2a03_people_add"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE person ADD COLUMN IF NOT EXISTS record_status text")
    op.execute("ALTER TABLE person ADD COLUMN IF NOT EXISTS source_origin text")
    op.execute("""
        UPDATE person SET record_status = verification_status
        WHERE record_status IS DISTINCT FROM verification_status
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION ghus_sync_person_v2_compat() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.verification_status IS NOT NULL AND NEW.record_status IS NOT NULL
               AND NEW.verification_status IS DISTINCT FROM NEW.record_status THEN
              RAISE EXCEPTION 'verification_status and record_status must match during compatibility period';
            END IF;
            NEW.verification_status := COALESCE(NEW.verification_status, NEW.record_status);
            NEW.record_status := COALESCE(NEW.record_status, NEW.verification_status);
          ELSIF NEW.verification_status IS DISTINCT FROM OLD.verification_status
                AND NEW.record_status IS NOT DISTINCT FROM OLD.record_status THEN
            NEW.record_status := NEW.verification_status;
          ELSIF NEW.record_status IS DISTINCT FROM OLD.record_status
                AND NEW.verification_status IS NOT DISTINCT FROM OLD.verification_status THEN
            NEW.verification_status := NEW.record_status;
          ELSIF NEW.verification_status IS DISTINCT FROM NEW.record_status THEN
            RAISE EXCEPTION 'verification_status and record_status changed inconsistently';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("DROP TRIGGER IF EXISTS person_v2_compat_sync ON person")
    op.execute("""
        CREATE TRIGGER person_v2_compat_sync
        BEFORE INSERT OR UPDATE OF verification_status,record_status ON person
        FOR EACH ROW EXECUTE FUNCTION ghus_sync_person_v2_compat()
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM person WHERE record_status IS DISTINCT FROM verification_status)
          THEN RAISE EXCEPTION 'refusing rollback: person status columns diverge'; END IF;
        END $$
    """)
    op.execute("DROP TRIGGER IF EXISTS person_v2_compat_sync ON person")
    op.execute("DROP FUNCTION IF EXISTS ghus_sync_person_v2_compat()")
    op.execute("ALTER TABLE person DROP COLUMN IF EXISTS record_status")
    op.execute("ALTER TABLE person DROP COLUMN IF EXISTS source_origin")
