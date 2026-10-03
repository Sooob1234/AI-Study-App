from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SourceSegmentDB(Base):
    """One timed piece of a video or audio transcript.

    For a video or audio source this plays the role that a page plays for
    a PDF: the raw extracted text, with where it came from.
    """

    __tablename__ = "source_segments"

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

    segment_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    start_seconds: Mapped[float] = mapped_column(
        Float,
        nullable=False
    )

    end_seconds: Mapped[float] = mapped_column(
        Float,
        nullable=False
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=""
    )
