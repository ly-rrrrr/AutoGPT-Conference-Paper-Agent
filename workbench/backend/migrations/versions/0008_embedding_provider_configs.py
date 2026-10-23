"""embedding provider configs

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "embedding_provider_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("secret_ref", sa.String(length=160), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("secret_ref"),
    )
    op.create_index("ix_embedding_provider_configs_is_default", "embedding_provider_configs", ["is_default"])
    op.create_index("ix_embedding_provider_configs_status", "embedding_provider_configs", ["status"])


def downgrade() -> None:
    op.drop_table("embedding_provider_configs")
