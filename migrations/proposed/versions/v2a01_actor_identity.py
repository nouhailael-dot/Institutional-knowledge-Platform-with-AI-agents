# ruff: noqa: E501
"""Detached proposal: Architecture V2 actor identity and location columns.

Schema-owner action required: set ``down_revision`` to the approved live head
before moving this file into ``migrations/versions``. It is deliberately outside
the live Alembic chain.
"""

from alembic import op

revision = "v2a01_actor"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='actor' AND column_name='actor_type')
             AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='actor' AND column_name='actor_category')
          THEN ALTER TABLE actor RENAME COLUMN actor_type TO actor_category; END IF;
          IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='actor' AND column_name='verification_status')
             AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='actor' AND column_name='record_status')
          THEN ALTER TABLE actor RENAME COLUMN verification_status TO record_status; END IF;
        END $$
    """)
    op.execute("""
        ALTER TABLE actor
          ADD COLUMN IF NOT EXISTS alternate_names text[] NOT NULL DEFAULT '{}',
          ADD COLUMN IF NOT EXISTS category_type text,
          ADD COLUMN IF NOT EXISTS category_note text,
          ADD COLUMN IF NOT EXISTS category_needs_review boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS website_domain text,
          ADD COLUMN IF NOT EXISTS state_code text,
          ADD COLUMN IF NOT EXISTS region_code text,
          ADD COLUMN IF NOT EXISTS latitude numeric(9,6),
          ADD COLUMN IF NOT EXISTS longitude numeric(9,6),
          ADD COLUMN IF NOT EXISTS is_multi_location boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS source_origin text NOT NULL DEFAULT 'imported',
          ADD COLUMN IF NOT EXISTS ghus_notes text
    """)
    for name in (
        "fk_actor_category_type",
        "fk_actor_region",
        "fk_actor_state",
        "fk_actor_source_origin",
        "ck_actor_record_status",
        "ck_actor_coordinates",
        "ck_actor_other_type_note",
    ):
        op.execute(f"ALTER TABLE actor DROP CONSTRAINT IF EXISTS {name}")
    op.execute("""ALTER TABLE actor ADD CONSTRAINT fk_actor_category_type
        FOREIGN KEY (actor_category, category_type)
        REFERENCES actor_category_type_definition(category_code, type_code) NOT VALID""")
    op.execute("""ALTER TABLE actor ADD CONSTRAINT fk_actor_region
        FOREIGN KEY (region_code) REFERENCES region_definition(region_code) NOT VALID""")
    op.execute("""ALTER TABLE actor ADD CONSTRAINT fk_actor_state
        FOREIGN KEY (state_code) REFERENCES region_state(state_code) NOT VALID""")
    op.execute("""ALTER TABLE actor ADD CONSTRAINT fk_actor_source_origin
        FOREIGN KEY (source_origin) REFERENCES source_origin_definition(origin_code) NOT VALID""")
    op.execute("""ALTER TABLE actor ADD CONSTRAINT ck_actor_record_status
        CHECK (record_status IN ('imported','parked','verified','rejected')) NOT VALID""")
    op.execute("""ALTER TABLE actor ADD CONSTRAINT ck_actor_coordinates CHECK (
        (latitude IS NULL) = (longitude IS NULL)
        AND (latitude IS NULL OR latitude BETWEEN -90 AND 90)
        AND (longitude IS NULL OR longitude BETWEEN -180 AND 180)) NOT VALID""")
    op.execute("""ALTER TABLE actor ADD CONSTRAINT ck_actor_other_type_note CHECK (
        category_type IS DISTINCT FROM 'other'
        OR nullif(btrim(category_note),'') IS NOT NULL) NOT VALID""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_actor_website_domain ON actor(lower(website_domain))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_actor_name_normalized ON actor(lower(name))")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_actor_alternate_names_gin ON actor USING gin(alternate_names)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_actor_geography ON actor(region_code,state_code,location_city)"
    )


def downgrade() -> None:
    for name in (
        "fk_actor_category_type",
        "fk_actor_region",
        "fk_actor_state",
        "fk_actor_source_origin",
        "ck_actor_record_status",
        "ck_actor_coordinates",
        "ck_actor_other_type_note",
    ):
        op.execute(f"ALTER TABLE actor DROP CONSTRAINT IF EXISTS {name}")
    for name in (
        "ix_actor_website_domain",
        "ix_actor_name_normalized",
        "ix_actor_alternate_names_gin",
        "ix_actor_geography",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.execute("""
        ALTER TABLE actor
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
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='actor' AND column_name='record_status')
             AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='actor' AND column_name='verification_status')
          THEN ALTER TABLE actor RENAME COLUMN record_status TO verification_status; END IF;
          IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='actor' AND column_name='actor_category')
             AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='actor' AND column_name='actor_type')
          THEN ALTER TABLE actor RENAME COLUMN actor_category TO actor_type; END IF;
        END $$
    """)
