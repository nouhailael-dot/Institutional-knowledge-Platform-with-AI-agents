"""add nutricrops gap fields

Revision ID: b8d1e6f2a903
Revises: a7c9d2e8f104
Create Date: 2026-07-18 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8d1e6f2a903"
down_revision: Union[str, Sequence[str], None] = "a7c9d2e8f104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("actor", sa.Column("funding_summary", sa.Text(), nullable=True))
    op.add_column(
        "actor_relevance",
        sa.Column("challenge_relevance_narrative", sa.Text(), nullable=True),
    )
    op.add_column("actor_relevance", sa.Column("source_links", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("actor_relevance", "source_links")
    op.drop_column("actor_relevance", "challenge_relevance_narrative")
    op.drop_column("actor", "funding_summary")
