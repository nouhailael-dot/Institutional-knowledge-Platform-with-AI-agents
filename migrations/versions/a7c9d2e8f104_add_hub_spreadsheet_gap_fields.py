"""add hub spreadsheet gap fields

Revision ID: a7c9d2e8f104
Revises: f3a9c1b2d4e5
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c9d2e8f104"
down_revision: Union[str, Sequence[str], None] = "f3a9c1b2d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hub", sa.Column("official_websites", sa.Text(), nullable=True))
    op.add_column("hub", sa.Column("strategic_value_summary", sa.Text(), nullable=True))
    op.add_column("hub", sa.Column("core_topic_strengths", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("hub", "core_topic_strengths")
    op.drop_column("hub", "strategic_value_summary")
    op.drop_column("hub", "official_websites")
