"""add description, thematic_focus, expected_attendance, access_type to event

These columns give a home to spreadsheet fields that previously had nowhere to
land and were being silently dropped:
  - Event Description / Short description   -> description
  - Thematic Focus / Core theme / 2026 Theme -> thematic_focus
  - Number of attendance (people)           -> expected_attendance (kept as text:
        the source has values like "Not confirmed", not just numbers)
  - Access type (UNGA/Climate Week)         -> access_type

Revision ID: c4e8a1d9f206
Revises: a7c2e91f4b03
Create Date: 2026-07-21 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8a1d9f206"
down_revision: Union[str, Sequence[str], None] = "a7c2e91f4b03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("event", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("event", sa.Column("thematic_focus", sa.Text(), nullable=True))
    op.add_column("event", sa.Column("expected_attendance", sa.String(length=120), nullable=True))
    op.add_column("event", sa.Column("access_type", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("event", "access_type")
    op.drop_column("event", "expected_attendance")
    op.drop_column("event", "thematic_focus")
    op.drop_column("event", "description")
    