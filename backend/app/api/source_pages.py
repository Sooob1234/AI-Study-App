from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.source import SourceDB
from app.models.source_page import SourcePageDB

router = APIRouter(
    tags=["Source Pages"]
)


@router.get("/sources/{source_id}/pages/")
def get_source_pages(
    source_id: int,
    db: Session = Depends(get_db)
):
    source = db.query(SourceDB).filter(
        SourceDB.id == source_id
    ).first()

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Source not found"
        )

    pages = db.query(SourcePageDB).filter(
        SourcePageDB.source_id == source_id
    ).order_by(
        SourcePageDB.page_number
    ).all()

    return [
        {
            "id": page.id,
            "source_id": page.source_id,
            "page_number": page.page_number,
            "text": page.text,
        }
        for page in pages
    ]
