"""research artifacts

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_briefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("tool_policy", sa.JSON(), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("output_preferences", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_briefs_status", "research_briefs", ["status"])

    op.create_table(
        "research_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_brief_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("generator", sa.String(length=120), nullable=False),
        sa.Column("generator_version", sa.String(length=80), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("uncertainty", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["research_brief_id"], ["research_briefs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["pipeline_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supersedes_artifact_id"], ["research_artifacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_artifacts_research_brief_id", "research_artifacts", ["research_brief_id"])
    op.create_index("ix_research_artifacts_workflow_run_id", "research_artifacts", ["workflow_run_id"])
    op.create_index("ix_research_artifacts_supersedes_artifact_id", "research_artifacts", ["supersedes_artifact_id"])
    op.create_index("ix_research_artifacts_artifact_type", "research_artifacts", ["artifact_type"])
    op.create_index("ix_research_artifacts_status", "research_artifacts", ["status"])

    op.create_table(
        "research_artifact_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("child_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("relation", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_artifact_id"], ["research_artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_artifact_id"], ["research_artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_artifact_id", "child_artifact_id", "relation", name="uq_research_artifact_dependency"),
    )
    op.create_index("ix_research_artifact_dependencies_parent_artifact_id", "research_artifact_dependencies", ["parent_artifact_id"])
    op.create_index("ix_research_artifact_dependencies_child_artifact_id", "research_artifact_dependencies", ["child_artifact_id"])

    op.create_table(
        "research_evidence_refs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=True),
        sa.Column("document_asset_id", sa.Uuid(), nullable=True),
        sa.Column("source_kind", sa.String(length=60), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("stance", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["research_artifact_id"], ["research_artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_asset_id"], ["document_assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_evidence_refs_research_artifact_id", "research_evidence_refs", ["research_artifact_id"])
    op.create_index("ix_research_evidence_refs_paper_id", "research_evidence_refs", ["paper_id"])
    op.create_index("ix_research_evidence_refs_document_asset_id", "research_evidence_refs", ["document_asset_id"])
    op.create_index("ix_research_evidence_refs_source_kind", "research_evidence_refs", ["source_kind"])
    op.create_index("ix_research_evidence_refs_source_sha256", "research_evidence_refs", ["source_sha256"])
    op.create_index("ix_research_evidence_refs_stance", "research_evidence_refs", ["stance"])

    op.create_table(
        "insight_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=False),
        sa.Column("epistemic_status", sa.String(length=40), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("counterarguments", sa.JSON(), nullable=False),
        sa.Column("open_questions", sa.JSON(), nullable=False),
        sa.Column("suggested_view", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["research_artifact_id"], ["research_artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("research_artifact_id"),
    )
    op.create_index("ix_insight_proposals_research_artifact_id", "insight_proposals", ["research_artifact_id"])
    op.create_index("ix_insight_proposals_epistemic_status", "insight_proposals", ["epistemic_status"])
    op.create_index("ix_insight_proposals_status", "insight_proposals", ["status"])


def downgrade() -> None:
    op.drop_table("insight_proposals")
    op.drop_table("research_evidence_refs")
    op.drop_table("research_artifact_dependencies")
    op.drop_table("research_artifacts")
    op.drop_table("research_briefs")
