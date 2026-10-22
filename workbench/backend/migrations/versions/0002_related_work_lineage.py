"""related work lineage

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reference_works",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("linked_paper_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("arxiv_id", sa.String(length=40), nullable=True),
        sa.Column("openalex_id", sa.String(length=80), nullable=True),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["linked_paper_id"], ["papers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reference_works_linked_paper_id", "reference_works", ["linked_paper_id"])
    op.create_index("ix_reference_works_normalized_title", "reference_works", ["normalized_title"])
    op.create_index("ix_reference_works_publication_year", "reference_works", ["publication_year"])
    op.create_index("ix_reference_works_doi", "reference_works", ["doi"])
    op.create_index("ix_reference_works_arxiv_id", "reference_works", ["arxiv_id"])
    op.create_index("ix_reference_works_openalex_id", "reference_works", ["openalex_id"])

    op.create_table(
        "paper_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("reference_work_id", sa.Uuid(), nullable=False),
        sa.Column("reference_key", sa.String(length=80), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("raw_reference", sa.Text(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("extractor", sa.String(length=120), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reference_work_id"], ["reference_works.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paper_id", "reference_key", "source_sha256", name="uq_paper_reference_source"),
    )
    op.create_index("ix_paper_references_paper_id", "paper_references", ["paper_id"])
    op.create_index("ix_paper_references_reference_work_id", "paper_references", ["reference_work_id"])
    op.create_index("ix_paper_references_source_sha256", "paper_references", ["source_sha256"])

    op.create_table(
        "related_work_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paper_reference_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column("context_text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("coordinates", sa.JSON(), nullable=False),
        sa.Column("evidence_key", sa.String(length=64), nullable=False),
        sa.Column("classifier", sa.String(length=120), nullable=False),
        sa.Column("classifier_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_reference_id"], ["paper_references.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paper_reference_id", "evidence_key", "classifier_version", name="uq_related_work_evidence_version"),
    )
    op.create_index("ix_related_work_evidence_paper_reference_id", "related_work_evidence", ["paper_reference_id"])
    op.create_index("ix_related_work_evidence_relation_type", "related_work_evidence", ["relation_type"])
    op.create_index("ix_related_work_evidence_status", "related_work_evidence", ["status"])
    op.create_index("ix_related_work_evidence_source_sha256", "related_work_evidence", ["source_sha256"])


def downgrade() -> None:
    op.drop_table("related_work_evidence")
    op.drop_table("paper_references")
    op.drop_table("reference_works")
