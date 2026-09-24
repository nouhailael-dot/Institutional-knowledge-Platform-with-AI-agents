# ruff: noqa: E501
"""Detached proposal: Architecture V2 canonical hub columns."""

from alembic import op

revision = "v2a02_hubs"
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
          ADD COLUMN IF NOT EXISTS radius_miles numeric(7,2) NOT NULL DEFAULT 200,
          ADD COLUMN IF NOT EXISTS center_frozen boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS center_method text NOT NULL DEFAULT 'phase1_member_density',
          ADD COLUMN IF NOT EXISTS approved_at timestamptz,
          ADD COLUMN IF NOT EXISTS approved_by text,
          ADD COLUMN IF NOT EXISTS phase1_definition text,
          ADD COLUMN IF NOT EXISTS source_origin text NOT NULL DEFAULT 'imported'
    """)
    op.execute("""
        ALTER TABLE hub_actor
          ADD COLUMN IF NOT EXISTS topic_id uuid,
          ADD COLUMN IF NOT EXISTS distance_miles numeric(8,2),
          ADD COLUMN IF NOT EXISTS assignment_outcome text NOT NULL DEFAULT 'legacy_membership',
          ADD COLUMN IF NOT EXISTS outside_radius boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS overlap_flag boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS source_id uuid
    """)
    hub_constraints = {
        "fk_hub_topic": "FOREIGN KEY (topic_id) REFERENCES topic(topic_id) NOT VALID",
        "fk_hub_center_state": "FOREIGN KEY (center_state_code) REFERENCES region_state(state_code) NOT VALID",
        "fk_hub_source_origin": "FOREIGN KEY (source_origin) REFERENCES source_origin_definition(origin_code) NOT VALID",
        "ck_hub_radius": "CHECK (radius_miles > 0 AND radius_miles <= 200) NOT VALID",
        "ck_hub_center_coordinates": "CHECK ((center_latitude IS NULL) = (center_longitude IS NULL) AND (center_latitude IS NULL OR center_latitude BETWEEN -90 AND 90) AND (center_longitude IS NULL OR center_longitude BETWEEN -180 AND 180)) NOT VALID",
    }
    member_constraints = {
        "fk_hub_actor_topic": "FOREIGN KEY (topic_id) REFERENCES topic(topic_id) NOT VALID",
        "fk_hub_actor_source": "FOREIGN KEY (source_id) REFERENCES source(source_id) NOT VALID",
        "ck_hub_actor_outcome": "CHECK (assignment_outcome IN ('assigned','legacy_membership','topic_location_review','topic_review','manual')) NOT VALID",
    }
    for name, clause in hub_constraints.items():
        op.execute(f"ALTER TABLE hub DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE hub ADD CONSTRAINT {name} {clause}")
    for name, clause in member_constraints.items():
        op.execute(f"ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE hub_actor ADD CONSTRAINT {name} {clause}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hub_topic ON hub(topic_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hub_actor_topic ON hub_actor(topic_id,actor_id)")


def downgrade() -> None:
    for name in ("fk_hub_actor_topic", "fk_hub_actor_source", "ck_hub_actor_outcome"):
        op.execute(f"ALTER TABLE hub_actor DROP CONSTRAINT IF EXISTS {name}")
    for name in (
        "fk_hub_topic",
        "fk_hub_center_state",
        "fk_hub_source_origin",
        "ck_hub_radius",
        "ck_hub_center_coordinates",
    ):
        op.execute(f"ALTER TABLE hub DROP CONSTRAINT IF EXISTS {name}")
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
