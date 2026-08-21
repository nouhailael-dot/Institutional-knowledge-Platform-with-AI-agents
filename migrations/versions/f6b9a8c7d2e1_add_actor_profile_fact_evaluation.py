"""add actor profile, capability fact, and evaluation tables

Revision ID: f6b9a8c7d2e1
Revises: d5f9b2e7a318
Create Date: 2026-08-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6b9a8c7d2e1"
down_revision: Union[str, Sequence[str], None] = "d5f9b2e7a318"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "actor_profile",
        sa.Column("actor_profile_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("profile_summary", sa.Text(), nullable=True),
        sa.Column("identity_summary", sa.Text(), nullable=True),
        sa.Column("technical_summary", sa.Text(), nullable=True),
        sa.Column("funding_summary", sa.Text(), nullable=True),
        sa.Column("lifecycle_summary", sa.Text(), nullable=True),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("verification_status", sa.String(length=30), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("generated_by", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["actor.actor_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source.source_id"]),
        sa.PrimaryKeyConstraint("actor_profile_id"),
        sa.UniqueConstraint("actor_id"),
    )

    op.create_table(
        "actor_capability_fact",
        sa.Column("actor_capability_fact_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("fact_type", sa.String(length=50), nullable=False),
        sa.Column("source_field", sa.String(length=80), nullable=False),
        sa.Column("fact_value", sa.Text(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(length=30), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("generated_by", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["actor.actor_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source.source_id"]),
        sa.PrimaryKeyConstraint("actor_capability_fact_id"),
        sa.UniqueConstraint("actor_id", "fact_type", "source_field", name="uq_actor_capability_fact"),
    )
    op.create_index("ix_actor_capability_fact_actor", "actor_capability_fact", ["actor_id"])
    op.create_index("ix_actor_capability_fact_type", "actor_capability_fact", ["fact_type"])

    op.create_table(
        "actor_evaluation",
        sa.Column("actor_evaluation_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("evaluation_context", sa.String(length=120), nullable=False),
        sa.Column("context_entity_type", sa.String(length=40), nullable=False),
        sa.Column("context_entity_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=3), nullable=True),
        sa.Column("evaluation_summary", sa.Text(), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("verification_status", sa.String(length=30), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("generated_by", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["actor.actor_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source.source_id"]),
        sa.PrimaryKeyConstraint("actor_evaluation_id"),
        sa.UniqueConstraint(
            "actor_id",
            "evaluation_context",
            "context_entity_type",
            "context_entity_id",
            name="uq_actor_evaluation_context",
        ),
    )
    op.create_index("ix_actor_evaluation_actor", "actor_evaluation", ["actor_id"])
    op.create_index("ix_actor_evaluation_context", "actor_evaluation", ["evaluation_context"])


def downgrade() -> None:
    op.drop_index("ix_actor_evaluation_context", table_name="actor_evaluation")
    op.drop_index("ix_actor_evaluation_actor", table_name="actor_evaluation")
    op.drop_table("actor_evaluation")
    op.drop_index("ix_actor_capability_fact_type", table_name="actor_capability_fact")
    op.drop_index("ix_actor_capability_fact_actor", table_name="actor_capability_fact")
    op.drop_table("actor_capability_fact")
    op.drop_table("actor_profile")
