"""Add the source_chunks table.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A database that ran the app between the introduction of chunking and
    # the introduction of migrations already has this table.
    if sa.inspect(op.get_bind()).has_table("source_chunks"):
        return

    op.create_table(
        "source_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("heading", sa.Text()),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_source_chunks_id", "source_chunks", ["id"])
    op.create_index("ix_source_chunks_source_id", "source_chunks", ["source_id"])


def downgrade() -> None:
    op.drop_table("source_chunks")
