"""Detached proposal: Architecture V2 canonical person columns."""

from alembic import op

revision = "v2a03_people"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='person' AND column_name='verification_status')
             AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='person' AND column_name='record_status')
          THEN ALTER TABLE person RENAME COLUMN verification_status TO record_status; END IF;
        END $$
    """)
    op.execute(
        "ALTER TABLE person ADD COLUMN IF NOT EXISTS source_origin text NOT NULL DEFAULT 'imported'"
    )
    op.execute("ALTER TABLE person DROP CONSTRAINT IF EXISTS fk_person_source_origin")
    op.execute(
        "ALTER TABLE person ADD CONSTRAINT fk_person_source_origin FOREIGN KEY (source_origin) REFERENCES source_origin_definition(origin_code) NOT VALID"
    )
    op.execute("ALTER TABLE person DROP CONSTRAINT IF EXISTS ck_person_record_status")
    op.execute(
        "ALTER TABLE person ADD CONSTRAINT ck_person_record_status CHECK (record_status IN ('imported','parked','verified','rejected')) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE person DROP CONSTRAINT IF EXISTS ck_person_record_status")
    op.execute("ALTER TABLE person DROP CONSTRAINT IF EXISTS fk_person_source_origin")
    op.execute("ALTER TABLE person DROP COLUMN IF EXISTS source_origin")
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='person' AND column_name='record_status')
             AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='person' AND column_name='verification_status')
          THEN ALTER TABLE person RENAME COLUMN record_status TO verification_status; END IF;
        END $$
    """)
