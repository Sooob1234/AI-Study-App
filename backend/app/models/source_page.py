from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SourcePageDB(Base):
    __tablename__ = "source_pages"

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

    page_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=""
    )
