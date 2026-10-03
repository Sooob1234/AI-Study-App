from sqlalchemy import ForeignKey, Integer, Text
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

    page_start: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    page_end: Mapped[int] = mapped_column(
        Integer,
        nullable=False
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
