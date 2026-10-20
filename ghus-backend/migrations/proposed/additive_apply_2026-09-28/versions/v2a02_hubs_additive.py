"""Additive half of V2 hub columns: nullable columns and indexes only."""

from alembic import op

revision = "v2a02_hubs_add"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE hub
          ADD COLUMN IF NOT EXISTS topic_id uuid,
          ADD COLUMN IF NOT EXISTS center_city text,
          ADD COLUMN IF NOT EXISTS center_state_code text,
          ADD COLUMN IF NOT EXISTS center_latitude numeric(9,6),
          ADD COLUMN IF NOT EXISTS center_longitude numeric(9,6),
          ADD COLUMN IF NOT EXISTS radius_miles numeric(7,2),
          ADD COLUMN IF NOT EXISTS center_frozen boolean,
          ADD COLUMN IF NOT EXISTS center_method text,
          ADD COLUMN IF NOT EXISTS approved_at timestamptz,
          ADD COLUMN IF NOT EXISTS approved_by text,
          ADD COLUMN IF NOT EXISTS phase1_definition text,
          ADD COLUMN IF NOT EXISTS source_origin text
    """)
    op.execute("""
        ALTER TABLE hub_actor
          ADD COLUMN IF NOT EXISTS topic_id uuid,
          ADD COLUMN IF NOT EXISTS distance_miles numeric(8,2),
          ADD COLUMN IF NOT EXISTS assignment_outcome text,
          ADD COLUMN IF NOT EXISTS outside_radius boolean,
          ADD COLUMN IF NOT EXISTS overlap_flag boolean,
          ADD COLUMN IF NOT EXISTS source_id uuid
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hub_topic ON hub(topic_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hub_actor_topic ON hub_actor(topic_id,actor_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_hub_actor_topic")
    op.execute("DROP INDEX IF EXISTS ix_hub_topic")
    op.execute("""ALTER TABLE hub_actor
        DROP COLUMN IF EXISTS topic_id, DROP COLUMN IF EXISTS distance_miles,
        DROP COLUMN IF EXISTS assignment_outcome, DROP COLUMN IF EXISTS outside_radius,
        DROP COLUMN IF EXISTS overlap_flag, DROP COLUMN IF EXISTS source_id""")
    op.execute("""ALTER TABLE hub
        DROP COLUMN IF EXISTS topic_id, DROP COLUMN IF EXISTS center_city,
        DROP COLUMN IF EXISTS center_state_code, DROP COLUMN IF EXISTS center_latitude,
        DROP COLUMN IF EXISTS center_longitude, DROP COLUMN IF EXISTS radius_miles,
        DROP COLUMN IF EXISTS center_frozen, DROP COLUMN IF EXISTS center_method,
        DROP COLUMN IF EXISTS approved_at, DROP COLUMN IF EXISTS approved_by,
        DROP COLUMN IF EXISTS phase1_definition, DROP COLUMN IF EXISTS source_origin""")
