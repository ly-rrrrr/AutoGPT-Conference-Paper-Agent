"""vector dimension compatibility boundary

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_vector_index_chunk_model_version",
        "vector_index_records",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_vector_index_chunk_model_dimension_version",
        "vector_index_records",
        ["document_chunk_id", "embedding_model", "embedding_dimension", "index_version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_vector_index_chunk_model_dimension_version",
        "vector_index_records",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_vector_index_chunk_model_version",
        "vector_index_records",
        ["document_chunk_id", "embedding_model", "index_version"],
    )
