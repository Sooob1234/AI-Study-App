from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column

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

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )


class SourceCreate(BaseModel):
    # INPUT_VALIDATION_V1
    # file_path is not accepted from outside: only the server decides
    # where an uploaded file is stored.
    title: str = Field(max_length=255)
    source_type: SourceType
    url: str | None = None
    duration: int | None = Field(default=None, ge=0)
    page_count: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title must not be empty")
        return value


class SourceResponse(BaseModel):
    id: int
    title: str
    source_type: str
    url: str | None
    file_path: str | None
    duration: int | None
    page_count: int | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
