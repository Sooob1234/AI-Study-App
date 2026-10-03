from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_own_source
from app.core.database import get_db
from app.models.source import SourceDB
from app.models.source_segment import SourceSegmentDB

router = APIRouter(
    tags=["Source Segments"]
)


@router.get("/sources/{source_id}/segments/")
def get_source_segments(
    source: SourceDB = Depends(get_own_source),
    db: Session = Depends(get_db)
):
    """The timed transcript of a video or audio source (empty for a PDF)."""
    segments = db.query(SourceSegmentDB).filter(
        SourceSegmentDB.source_id == source.id
    ).order_by(
        SourceSegmentDB.segment_index
    ).all()

    return [
        {
            "id": segment.id,
            "source_id": segment.source_id,
            "segment_index": segment.segment_index,
            "start_seconds": segment.start_seconds,
            "end_seconds": segment.end_seconds,
            "text": segment.text,
        }
        for segment in segments
    ]
