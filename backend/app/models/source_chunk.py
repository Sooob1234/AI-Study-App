from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SourceChunkDB(Base):
    __tablename__ = "source_chunks"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    # Where the chunk comes from: pages for a PDF, time for video or audio.
    page_start: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    page_end: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    start_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )

    end_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )

    # The section this chunk sits under, e.g. "3- ... › 3 -2- ...".
    heading: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=""
    )
