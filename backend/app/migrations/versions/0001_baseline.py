"""Baseline: projects, sources, their link table, and source pages.

This is the database as it was before migrations were introduced. A database
that already has these tables is marked as being at this step without
running it (see app/core/migrate.py).

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_projects_id", "projects", ["id"])

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("file_path", sa.Text()),
        sa.Column("duration", sa.Integer()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sources_id", "sources", ["id"])

    op.create_table(
        "project_sources",
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "source_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_source_pages_id", "source_pages", ["id"])
    op.create_index("ix_source_pages_source_id", "source_pages", ["source_id"])


def downgrade() -> None:
    op.drop_table("source_pages")
    op.drop_table("project_sources")
    op.drop_table("sources")
    op.drop_table("projects")
