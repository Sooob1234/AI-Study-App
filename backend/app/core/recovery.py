"""Clean-up after the app was stopped while it was still working."""

from app.core.database import SessionLocal
from app.models.output import OutputDB
from app.models.source import SourceDB

INTERRUPTED = "INTERRUPTED"


def fail_interrupted_sources() -> int:
    """Mark sources and outputs that were cut off by a restart as FAILED.

    Processing runs inside the app itself, so a source still PROCESSING
    when the app starts can never finish on its own. Returns how many
    sources were marked. An interrupted audio source can be retried.
    """
    db = SessionLocal()

    try:
        count = db.query(SourceDB).filter(
            SourceDB.status == "PROCESSING"
        ).update({
            "status": "FAILED",
            "status_detail": INTERRUPTED,
        })
        # The same holds for AI outputs that were being made.
        count += db.query(OutputDB).filter(
            OutputDB.status == "PROCESSING"
        ).update({
            "status": "FAILED",
            "status_detail": INTERRUPTED,
        })
        db.commit()
        return count
    finally:
        db.close()
