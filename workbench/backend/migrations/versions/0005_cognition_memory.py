"""cognition memory and artifacts

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cognition_paper_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=True),
        sa.Column("last_seen_run_id", sa.Uuid(), nullable=True),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("program_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reuse_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["paper_analyses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_seen_run_id"], ["pipeline_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paper_id"),
    )
    op.create_index("ix_cognition_paper_memories_analysis_id", "cognition_paper_memories", ["analysis_id"])
    op.create_index("ix_cognition_paper_memories_input_fingerprint", "cognition_paper_memories", ["input_fingerprint"])
    op.create_index("ix_cognition_paper_memories_last_seen_run_id", "cognition_paper_memories", ["last_seen_run_id"])
    op.create_index("ix_cognition_paper_memories_paper_id", "cognition_paper_memories", ["paper_id"])
    op.create_index("ix_cognition_paper_memories_status", "cognition_paper_memories", ["status"])

    op.create_table(
        "cognition_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("generator", sa.String(length=120), nullable=False),
        sa.Column("generator_version", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("uncertainty", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["supersedes_artifact_id"], ["cognition_artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["pipeline_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_type", "input_fingerprint", "generator_version", name="uq_cognition_artifact_cache"),
    )
    op.create_index("ix_cognition_artifacts_artifact_type", "cognition_artifacts", ["artifact_type"])
    op.create_index("ix_cognition_artifacts_input_fingerprint", "cognition_artifacts", ["input_fingerprint"])
    op.create_index("ix_cognition_artifacts_status", "cognition_artifacts", ["status"])
    op.create_index("ix_cognition_artifacts_supersedes_artifact_id", "cognition_artifacts", ["supersedes_artifact_id"])
    op.create_index("ix_cognition_artifacts_workflow_run_id", "cognition_artifacts", ["workflow_run_id"])

    op.create_table(
        "cognition_artifact_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=True),
        sa.Column("stance", sa.String(length=40), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["paper_analyses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["artifact_id"], ["cognition_artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "paper_id", "stance", name="uq_cognition_artifact_source"),
    )
    op.create_index("ix_cognition_artifact_sources_analysis_id", "cognition_artifact_sources", ["analysis_id"])
    op.create_index("ix_cognition_artifact_sources_artifact_id", "cognition_artifact_sources", ["artifact_id"])
    op.create_index("ix_cognition_artifact_sources_paper_id", "cognition_artifact_sources", ["paper_id"])
    op.create_index("ix_cognition_artifact_sources_stance", "cognition_artifact_sources", ["stance"])


def downgrade() -> None:
    op.drop_table("cognition_artifact_sources")
    op.drop_table("cognition_artifacts")
    op.drop_table("cognition_paper_memories")
