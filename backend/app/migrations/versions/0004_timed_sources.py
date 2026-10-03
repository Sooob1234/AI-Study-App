"""Support sources with time instead of pages, and a reason for a status.

- source_segments: timed transcript pieces of a video or audio source.
- source_chunks: page numbers become optional; start and end time added.
- sources: status_detail says why a source is NEEDS_REVIEW or FAILED.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_source_segments_id", "source_segments", ["id"])
    op.create_index(
        "ix_source_segments_source_id", "source_segments", ["source_id"]
    )

    op.alter_column("source_chunks", "page_start", nullable=True)
    op.alter_column("source_chunks", "page_end", nullable=True)
    op.add_column("source_chunks", sa.Column("start_seconds", sa.Float()))
    op.add_column("source_chunks", sa.Column("end_seconds", sa.Float()))

    op.add_column("sources", sa.Column("status_detail", sa.String(50)))


def downgrade() -> None:
    op.drop_column("sources", "status_detail")
    op.drop_column("source_chunks", "end_seconds")
    op.drop_column("source_chunks", "start_seconds")
    op.alter_column("source_chunks", "page_end", nullable=False)
    op.alter_column("source_chunks", "page_start", nullable=False)
    op.drop_table("source_segments")
