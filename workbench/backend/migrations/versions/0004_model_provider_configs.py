"""model provider configs

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23
"""

from datetime import UTC, datetime
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_CONFIG_ID = uuid.UUID("8dc571e7-2b34-4c29-8bb7-b8fc9eea0001")


def upgrade() -> None:
    table = op.create_table(
        "model_provider_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("secret_ref", sa.String(length=160), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("secret_ref"),
    )
    op.create_index(
        "ix_model_provider_configs_is_default",
        "model_provider_configs",
        ["is_default"],
    )
    op.create_index(
        "ix_model_provider_configs_status",
        "model_provider_configs",
        ["status"],
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        table,
        [
            {
                "id": DEFAULT_CONFIG_ID,
                "name": "AIHubMix GPT-6 Sol",
                "provider": "AIHubMix",
                "base_url": "https://aihubmix.com/v1",
                "model_name": "gpt-6-sol",
                "secret_ref": str(DEFAULT_CONFIG_ID),
                "is_default": True,
                "status": "ACTIVE",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("model_provider_configs")
