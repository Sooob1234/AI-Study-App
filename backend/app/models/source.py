from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.core.database import Base


class SourceType(str, Enum):
    YOUTUBE = "YOUTUBE"
    PDF = "PDF"
    AUDIO = "AUDIO"
    PODCAST = "PODCAST"


class SourceStatus(str, Enum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


project_sources = Table(
    "project_sources",
    Base.metadata,
    Column(
        "project_id",
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "source_id",
        Integer,
        ForeignKey("sources.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class SourceDB(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # The owner. Empty only for rows made before accounts existed.
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    source_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False
    )

    url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    file_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    duration: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    page_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default=SourceStatus.PROCESSING.value,
        nullable=False
    )

    # Language code such as "fa" or "en", when it is known.
    language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True
    )

    # Why the source is NEEDS_REVIEW or FAILED, as a short code such as
    # NO_TEXT. Empty when there is nothing to report.
    status_detail: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now
    )


class SourceResponse(BaseModel):
    id: int
    title: str
    source_type: str
    url: str | None
    duration: int | None
    page_count: int | None
    language: str | None
    status: str
    status_detail: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
