from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.core.database import Base
from app.models.validation import MAX_DB_INTEGER


class GoalType(str, Enum):
    QUICK_LEARN = "QUICK_LEARN"
    EXAM_PREP = "EXAM_PREP"
    SUMMARY = "SUMMARY"
    QUIZ = "QUIZ"
    PRESENTATION = "PRESENTATION"


class ScopeType(str, Enum):
    ONE_SOURCE = "ONE_SOURCE"
    SELECTED_SOURCES = "SELECTED_SOURCES"
    ALL_SOURCES = "ALL_SOURCES"


class AIMode(str, Enum):
    SOURCE_ONLY = "SOURCE_ONLY"
    SOURCE_PLUS_AI = "SOURCE_PLUS_AI"


output_sources = Table(
    "output_sources",
    Base.metadata,
    Column(
        "output_id",
        Integer,
        ForeignKey("outputs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "source_id",
        Integer,
        ForeignKey("sources.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class OutputDB(Base):
    """Something the AI made from one or more sources (a summary, a quiz)."""

    __tablename__ = "outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    goal_type: Mapped[str] = mapped_column(String(30), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)

    # PROCESSING, READY, NEEDS_REVIEW or FAILED, with a reason code.
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    status_detail: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # How far the making has come, in parts of the source.
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The result itself, as structured data that the app displays.
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class OutputCreate(BaseModel):
    goal_type: GoalType
    mode: AIMode = AIMode.SOURCE_ONLY
    scope_type: ScopeType = ScopeType.ONE_SOURCE
    source_ids: list[Annotated[int, Field(ge=1, le=MAX_DB_INTEGER)]] = Field(
        min_length=1, max_length=50
    )


class OutputSummary(BaseModel):
    """An output without its content, for lists."""

    id: int
    project_id: int
    title: str
    goal_type: str
    scope_type: str
    mode: str
    status: str
    status_detail: str | None
    progress_done: int
    progress_total: int
    created_at: datetime
    source_ids: list[int] = []

    model_config = ConfigDict(from_attributes=True)


class OutputResponse(OutputSummary):
    content: dict[str, Any] | None = None

