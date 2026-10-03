from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.source import SourceDB
from app.models.source_chunk import SourceChunkDB
from app.models.source_page import SourcePageDB
from app.services.chunking import build_chunks

router = APIRouter(
    tags=["Source Chunks"]
)


def save_chunks(db: Session, source_id: int, pages: list[tuple[int, str]]) -> int:
    """Replace the chunks of a source with fresh ones. Does not commit."""
    db.execute(
        delete(SourceChunkDB).where(SourceChunkDB.source_id == source_id)
    )

    chunks = build_chunks(pages)

    for chunk in chunks:
        db.add(SourceChunkDB(
            source_id=source_id,
            chunk_index=chunk.chunk_index,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            heading=chunk.heading,
            text=chunk.text,
        ))

    return len(chunks)


def _get_source(db: Session, source_id: int) -> SourceDB:
    source = db.query(SourceDB).filter(
        SourceDB.id == source_id
    ).first()

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Source not found"
        )

    return source


@router.get("/sources/{source_id}/chunks/")
def get_source_chunks(
    source_id: int,
    db: Session = Depends(get_db)
):
    _get_source(db, source_id)

    chunks = db.query(SourceChunkDB).filter(
        SourceChunkDB.source_id == source_id
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
            "heading": chunk.heading,
            "text": chunk.text,
        }
        for chunk in chunks
    ]


@router.post("/sources/{source_id}/chunks/")
def rebuild_source_chunks(
    source_id: int,
    db: Session = Depends(get_db)
):
    """Build the chunks again from the pages already saved for a source.

    Useful for sources uploaded before chunking existed.
    """
    _get_source(db, source_id)

    pages = db.query(SourcePageDB).filter(
        SourcePageDB.source_id == source_id
    ).order_by(
        SourcePageDB.page_number
    ).all()

    count = save_chunks(
        db,
        source_id,
        [(page.page_number, page.text) for page in pages]
    )
    db.commit()

    return {
        "source_id": source_id,
        "chunk_count": count,
    }
