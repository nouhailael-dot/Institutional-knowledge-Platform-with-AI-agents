"""Additive half of V2 event columns: nullable columns only."""

from alembic import op

revision = "v2a04_events_add"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""ALTER TABLE event
        ADD COLUMN IF NOT EXISTS record_status text,
        ADD COLUMN IF NOT EXISTS source_origin text,
        ADD COLUMN IF NOT EXISTS date_status text,
        ADD COLUMN IF NOT EXISTS start_date date,
        ADD COLUMN IF NOT EXISTS end_date date,
        ADD COLUMN IF NOT EXISTS ghus_notes text""")


def downgrade() -> None:
    op.execute("""ALTER TABLE event
        DROP COLUMN IF EXISTS record_status, DROP COLUMN IF EXISTS source_origin,
        DROP COLUMN IF EXISTS date_status, DROP COLUMN IF EXISTS start_date,
        DROP COLUMN IF EXISTS end_date, DROP COLUMN IF EXISTS ghus_notes""")
