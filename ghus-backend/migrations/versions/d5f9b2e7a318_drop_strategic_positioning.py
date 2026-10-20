"""drop strategic_positioning and strategic_value_narrative from event_scoring

These two fields correspond to the 'Strategic Positioning' and 'Potential
Strategic Value For UM6P' spreadsheet columns, which were intentionally dropped
in the final event mapping (UM6P_EVENT_VF). Removing the columns keeps the
schema aligned with the source of truth.

Reversible: downgrade re-adds both as nullable Text (data is not restored).

Revision ID: d5f9b2e7a318
Revises: c4e8a1d9f206
Create Date: 2026-07-21 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5f9b2e7a318"
down_revision: Union[str, Sequence[str], None] = "c4e8a1d9f206"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("event_scoring", "strategic_positioning")
    op.drop_column("event_scoring", "strategic_value_narrative")


def downgrade() -> None:
    op.add_column("event_scoring",
                  sa.Column("strategic_value_narrative", sa.Text(), nullable=True))
    op.add_column("event_scoring",
                  sa.Column("strategic_positioning", sa.Text(), nullable=True))