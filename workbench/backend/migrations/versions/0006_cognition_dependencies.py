"""cognition artifact dependencies

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cognition_artifact_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("relation", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["cognition_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_artifact_id"],
            ["cognition_artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            "depends_on_artifact_id",
            "relation",
            name="uq_cognition_artifact_dependency",
        ),
    )
    op.create_index(
        "ix_cognition_artifact_dependencies_artifact_id",
        "cognition_artifact_dependencies",
        ["artifact_id"],
    )
    op.create_index(
        "ix_cognition_artifact_dependencies_depends_on_artifact_id",
        "cognition_artifact_dependencies",
        ["depends_on_artifact_id"],
    )
    op.create_index(
        "ix_cognition_artifact_dependencies_relation",
        "cognition_artifact_dependencies",
        ["relation"],
    )


def downgrade() -> None:
    op.drop_table("cognition_artifact_dependencies")
