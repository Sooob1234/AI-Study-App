"""Shared rules for sources that are processed in the background."""

import logging
import time

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.limits import MAX_PROCESSING_PER_USER
from app.models.source import SourceDB

logger = logging.getLogger(__name__)


def require_processing_slot(db: Session, user_id: int) -> None:
    """Refuse a new job while the user already has too many in processing.

    Keeps one user from filling the waiting lines for everybody else.
    """
    in_processing = db.query(SourceDB).filter(
        SourceDB.user_id == user_id,
        SourceDB.status == "PROCESSING"
    ).count()

    if in_processing >= MAX_PROCESSING_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=(
                f"{MAX_PROCESSING_PER_USER} of your sources are still being "
                "processed; wait for one to finish"
            )
        )


def claim_failed_source(db: Session, source_id: int) -> bool:
    """Move a source from FAILED to PROCESSING, as one indivisible step.

    Returns False if it was not FAILED (for example because another
    request claimed it a moment earlier), so that a source can never be
    given to two jobs at once. Commits.
    """
    result = db.execute(
        update(SourceDB)
        .where(SourceDB.id == source_id, SourceDB.status == "FAILED")
        .values(status="PROCESSING", status_detail=None)
    )
    db.commit()

    return result.rowcount == 1


def mark_failed(source_id: int, code: str, attempts: int = 3) -> None:
    """Record that the processing of a source failed.

    Only a source that is still PROCESSING is changed. Tried a few times,
    because this is what keeps a source from staying PROCESSING for ever.
    """
    for attempt in range(attempts):
        db = SessionLocal()
        try:
            db.execute(
                update(SourceDB)
                .where(
                    SourceDB.id == source_id,
                    SourceDB.status == "PROCESSING"
                )
                .values(status="FAILED", status_detail=code)
            )
            db.commit()
            return
        except Exception:
            db.rollback()
            logger.exception(
                "Could not record the failure of source %s (attempt %s)",
                source_id, attempt + 1,
            )
            time.sleep(1 + attempt)
        finally:
            db.close()


def still_processing(db: Session, source_id: int) -> SourceDB | None:
    """The source, locked for writing, if it is still waiting for a result.

    A job must store its result only on a source that is still PROCESSING:
    the source may have been deleted, or already finished by another job.
    """
    return db.query(SourceDB).filter(
        SourceDB.id == source_id,
        SourceDB.status == "PROCESSING"
    ).with_for_update().first()
