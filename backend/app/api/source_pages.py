from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_own_source
from app.core.database import get_db
from app.models.source import SourceDB
from app.models.source_page import SourcePageDB

router = APIRouter(
    tags=["Source Pages"]
)


@router.get("/sources/{source_id}/pages/")
def get_source_pages(
    source: SourceDB = Depends(get_own_source),
    db: Session = Depends(get_db)
):
    pages = db.query(SourcePageDB).filter(
        SourcePageDB.source_id == source.id
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
