"""asset index and durable job foundation

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipeline_runs", sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pipeline_runs", sa.Column("lease_owner", sa.String(length=160), nullable=True))
    op.add_column("pipeline_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pipeline_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pipeline_runs", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("pipeline_runs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("pipeline_runs", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_index("ix_pipeline_runs_available_at", "pipeline_runs", ["available_at"])
    op.create_index("ix_pipeline_runs_lease_owner", "pipeline_runs", ["lease_owner"])
    op.create_index("ix_pipeline_runs_lease_expires_at", "pipeline_runs", ["lease_expires_at"])

    op.add_column("document_assets", sa.Column("source_uri", sa.Text(), nullable=True))
    op.add_column("document_assets", sa.Column("media_type", sa.String(length=120), nullable=True))
    op.add_column("document_assets", sa.Column("byte_size", sa.BigInteger(), nullable=True))
    op.add_column("document_assets", sa.Column("parent_asset_id", sa.Uuid(), nullable=True))
    op.add_column("document_assets", sa.Column("derivation", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column("document_assets", sa.Column("metadata_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.create_foreign_key(
        "fk_document_assets_parent_asset_id",
        "document_assets",
        "document_assets",
        ["parent_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_document_assets_parent_asset_id", "document_assets", ["parent_asset_id"])

    op.create_table(
        "document_asset_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_asset_id", sa.Uuid(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("media_type", sa.String(length=120), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("producer", sa.String(length=120), nullable=True),
        sa.Column("producer_version", sa.String(length=80), nullable=True),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_asset_id"], ["document_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_asset_id", "content_sha256", name="uq_document_asset_revision_content"),
    )
    op.create_index("ix_document_asset_revisions_document_asset_id", "document_asset_revisions", ["document_asset_id"])
    op.create_index("ix_document_asset_revisions_content_sha256", "document_asset_revisions", ["content_sha256"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_revision_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_key", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("section_path", sa.JSON(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_revision_id"], ["document_asset_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_revision_id", "chunk_key", name="uq_document_chunk_revision_key"),
    )
    op.create_index("ix_document_chunks_asset_revision_id", "document_chunks", ["asset_revision_id"])
    op.create_index("ix_document_chunks_paper_id", "document_chunks", ["paper_id"])
    op.create_index("ix_document_chunks_kind", "document_chunks", ["kind"])
    op.create_index("ix_document_chunks_content_sha256", "document_chunks", ["content_sha256"])

    op.create_table(
        "vector_index_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("collection_name", sa.String(length=255), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=False),
        sa.Column("embedding_model", sa.String(length=160), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("index_version", sa.String(length=80), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_chunk_id", "embedding_model", "index_version", name="uq_vector_index_chunk_model_version"),
        sa.UniqueConstraint("collection_name", "entity_id", name="uq_vector_collection_entity"),
    )
    op.create_index("ix_vector_index_records_document_chunk_id", "vector_index_records", ["document_chunk_id"])
    op.create_index("ix_vector_index_records_collection_name", "vector_index_records", ["collection_name"])
    op.create_index("ix_vector_index_records_embedding_model", "vector_index_records", ["embedding_model"])
    op.create_index("ix_vector_index_records_content_sha256", "vector_index_records", ["content_sha256"])
    op.create_index("ix_vector_index_records_status", "vector_index_records", ["status"])


def downgrade() -> None:
    op.drop_table("vector_index_records")
    op.drop_table("document_chunks")
    op.drop_table("document_asset_revisions")
    op.drop_index("ix_document_assets_parent_asset_id", table_name="document_assets")
    op.drop_constraint("fk_document_assets_parent_asset_id", "document_assets", type_="foreignkey")
    op.drop_column("document_assets", "metadata_payload")
    op.drop_column("document_assets", "derivation")
    op.drop_column("document_assets", "parent_asset_id")
    op.drop_column("document_assets", "byte_size")
    op.drop_column("document_assets", "media_type")
    op.drop_column("document_assets", "source_uri")
    op.drop_index("ix_pipeline_runs_lease_expires_at", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_lease_owner", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_available_at", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "last_error")
    op.drop_column("pipeline_runs", "max_attempts")
    op.drop_column("pipeline_runs", "attempt_count")
    op.drop_column("pipeline_runs", "heartbeat_at")
    op.drop_column("pipeline_runs", "lease_expires_at")
    op.drop_column("pipeline_runs", "lease_owner")
    op.drop_column("pipeline_runs", "available_at")
