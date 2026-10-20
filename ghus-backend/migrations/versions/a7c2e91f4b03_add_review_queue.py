"""add review_queue table for entity resolution human-in-the-loop

Revision ID: a7c2e91f4b03
Revises: f3a9c1b2d4e5
Create Date: 2026-07-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c2e91f4b03'
down_revision: Union[str, Sequence[str], None] = 'b8d1e6f2a903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'review_queue',
        sa.Column('review_id', sa.UUID(), nullable=False),
        # actor_id_a < actor_id_b always, so a pair is stored once
        sa.Column('actor_id_a', sa.UUID(), nullable=False),
        sa.Column('actor_id_b', sa.UUID(), nullable=False),
        sa.Column('score', sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column('model', sa.String(length=60), nullable=True),
        sa.Column('features', sa.JSON(), nullable=True),
        # pending | same | different | hierarchy | skipped
        sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('decided_by', sa.String(length=120), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('merge_id', sa.UUID(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['actor_id_a'], ['actor.actor_id'], ),
        sa.ForeignKeyConstraint(['actor_id_b'], ['actor.actor_id'], ),
        sa.ForeignKeyConstraint(['merge_id'], ['actor_merge_log.merge_id'], ),
        sa.PrimaryKeyConstraint('review_id'),
        sa.UniqueConstraint('actor_id_a', 'actor_id_b', name='uq_review_pair'),
    )
    op.create_index('ix_review_queue_status', 'review_queue', ['status'])
    op.create_index('ix_review_queue_score', 'review_queue', ['score'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_review_queue_score', table_name='review_queue')
    op.drop_index('ix_review_queue_status', table_name='review_queue')
    op.drop_table('review_queue')