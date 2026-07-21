"""add actor_merge_log and actor soft-delete for entity resolution

Revision ID: f3a9c1b2d4e5
Revises: e51c426bf42a
Create Date: 2026-07-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a9c1b2d4e5'
down_revision: Union[str, Sequence[str], None] = 'e51c426bf42a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # soft-delete marker on actor: non-null => this actor was merged into another
    op.add_column('actor', sa.Column('merged_into_actor_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_actor_merged_into_actor', 'actor', 'actor',
        ['merged_into_actor_id'], ['actor_id'],
    )

    # reversible merge log: pre_merge_state stores the loser row + ref counts as JSONB
    op.create_table(
        'actor_merge_log',
        sa.Column('merge_id', sa.UUID(), nullable=False),
        sa.Column('winner_actor_id', sa.UUID(), nullable=False),
        sa.Column('loser_actor_id', sa.UUID(), nullable=False),
        sa.Column('score', sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('decided_by', sa.String(length=120), nullable=True),
        sa.Column('decided_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('pre_merge_state', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'applied'"), nullable=False),
        sa.Column('reverted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['winner_actor_id'], ['actor.actor_id'], ),
        sa.ForeignKeyConstraint(['loser_actor_id'], ['actor.actor_id'], ),
        sa.PrimaryKeyConstraint('merge_id'),
    )
    op.create_index('ix_actor_merge_log_loser', 'actor_merge_log', ['loser_actor_id'])
    op.create_index('ix_actor_merge_log_winner', 'actor_merge_log', ['winner_actor_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_actor_merge_log_winner', table_name='actor_merge_log')
    op.drop_index('ix_actor_merge_log_loser', table_name='actor_merge_log')
    op.drop_table('actor_merge_log')
    op.drop_constraint('fk_actor_merged_into_actor', 'actor', type_='foreignkey')
    op.drop_column('actor', 'merged_into_actor_id')