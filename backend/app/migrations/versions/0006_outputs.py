"""Add outputs: what the AI makes from sources (summaries, later quizzes).

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("goal_type", sa.String(30), nullable=False),
        sa.Column("scope_type", sa.String(30), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("status_detail", sa.String(50)),
        sa.Column("progress_done", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("content", JSONB()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_outputs_id", "outputs", ["id"])
    op.create_index("ix_outputs_user_id", "outputs", ["user_id"])
    op.create_index("ix_outputs_project_id", "outputs", ["project_id"])

    op.create_table(
        "output_sources",
        sa.Column(
            "output_id",
            sa.Integer(),
            sa.ForeignKey("outputs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("output_sources")
    op.drop_table("outputs")
