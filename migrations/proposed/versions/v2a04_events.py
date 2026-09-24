# ruff: noqa: E501
"""Detached proposal: Architecture V2 canonical event columns."""

from alembic import op

revision = "v2a04_events"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""ALTER TABLE event
        ADD COLUMN IF NOT EXISTS record_status text NOT NULL DEFAULT 'imported',
        ADD COLUMN IF NOT EXISTS source_origin text NOT NULL DEFAULT 'imported',
        ADD COLUMN IF NOT EXISTS date_status text NOT NULL DEFAULT 'unconfirmed',
        ADD COLUMN IF NOT EXISTS start_date date,
        ADD COLUMN IF NOT EXISTS end_date date,
        ADD COLUMN IF NOT EXISTS ghus_notes text""")
    constraints = {
        "fk_event_source_origin": "FOREIGN KEY (source_origin) REFERENCES source_origin_definition(origin_code) NOT VALID",
        "ck_event_record_status": "CHECK (record_status IN ('imported','parked','verified','rejected')) NOT VALID",
        "ck_event_date_status": "CHECK (date_status IN ('upcoming','past','unconfirmed')) NOT VALID",
        "ck_event_date_order": "CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date) NOT VALID",
    }
    for name, clause in constraints.items():
        op.execute(f"ALTER TABLE event DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE event ADD CONSTRAINT {name} {clause}")


def downgrade() -> None:
    for name in (
        "fk_event_source_origin",
        "ck_event_record_status",
        "ck_event_date_status",
        "ck_event_date_order",
    ):
        op.execute(f"ALTER TABLE event DROP CONSTRAINT IF EXISTS {name}")
    op.execute("""ALTER TABLE event
        DROP COLUMN IF EXISTS record_status, DROP COLUMN IF EXISTS source_origin,
        DROP COLUMN IF EXISTS date_status, DROP COLUMN IF EXISTS start_date,
        DROP COLUMN IF EXISTS end_date, DROP COLUMN IF EXISTS ghus_notes""")
