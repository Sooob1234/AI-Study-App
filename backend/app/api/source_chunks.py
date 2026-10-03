from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.deps import get_own_source
from app.core.database import get_db
from app.models.source import SourceDB
from app.models.source_chunk import SourceChunkDB
from app.models.source_page import SourcePageDB
from app.models.source_segment import SourceSegmentDB
from app.services.chunking import Chunk, build_chunks, build_time_chunks

router = APIRouter(
    tags=["Source Chunks"]
)


def save_chunks(db: Session, source_id: int, chunks: list[Chunk]) -> int:
    """Replace the chunks of a source with the given ones. Does not commit."""
    db.execute(
        delete(SourceChunkDB).where(SourceChunkDB.source_id == source_id)
    )

    for chunk in chunks:
        db.add(SourceChunkDB(
            source_id=source_id,
            chunk_index=chunk.chunk_index,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            start_seconds=chunk.start_seconds,
            end_seconds=chunk.end_seconds,
            heading=chunk.heading,
            text=chunk.text,
        ))

    return len(chunks)


@router.get("/sources/{source_id}/chunks/")
def get_source_chunks(
    source: SourceDB = Depends(get_own_source),
    db: Session = Depends(get_db)
):
    chunks = db.query(SourceChunkDB).filter(
        SourceChunkDB.source_id == source.id
    ).order_by(
        SourceChunkDB.chunk_index
    ).all()

    return [
        {
            "id": chunk.id,
            "source_id": chunk.source_id,
            "chunk_index": chunk.chunk_index,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "start_seconds": chunk.start_seconds,
            "end_seconds": chunk.end_seconds,
            "heading": chunk.heading,
            "text": chunk.text,
        }
        for chunk in chunks
    ]


@router.post("/sources/{source_id}/chunks/")
def rebuild_source_chunks(
    source: SourceDB = Depends(get_own_source),
    db: Session = Depends(get_db)
):
    """Build the chunks again from the saved pages or transcript of a source.

    Useful for sources uploaded before chunking existed.
    """
    source_id = source.id

    segments = db.query(SourceSegmentDB).filter(
        SourceSegmentDB.source_id == source_id
    ).order_by(
        SourceSegmentDB.segment_index
    ).all()

    if segments:
        chunks = build_time_chunks([
            (segment.start_seconds, segment.end_seconds, segment.text)
            for segment in segments
        ])
    else:
        pages = db.query(SourcePageDB).filter(
            SourcePageDB.source_id == source_id
        ).order_by(
            SourcePageDB.page_number
        ).all()

        chunks = build_chunks(
            [(page.page_number, page.text) for page in pages]
        )

    count = save_chunks(db, source_id, chunks)
    db.commit()

    return {
        "source_id": source_id,
        "chunk_count": count,
    }
