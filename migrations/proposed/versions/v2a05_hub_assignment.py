"""Detached additive proposal: Phase 6 hub center audit metadata."""

from alembic import op

revision = "v2a05_hub_assignment"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""ALTER TABLE hub
        ADD COLUMN IF NOT EXISTS center_method_version text,
        ADD COLUMN IF NOT EXISTS center_computed_at timestamptz""")


def downgrade() -> None:
    op.execute("""ALTER TABLE hub
        DROP COLUMN IF EXISTS center_computed_at,
        DROP COLUMN IF EXISTS center_method_version""")
