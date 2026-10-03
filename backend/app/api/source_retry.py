import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.audio_upload import require_transcriber, start_processing
from app.api.deps import get_current_user, get_own_source
from app.api.youtube import start_fetching
from app.core import worker
from app.core.config import to_disk_path
from app.core.database import get_db
from app.core.processing import claim_failed_source, require_processing_slot
from app.models.source import SourceDB, SourceResponse
from app.models.user import UserDB
from app.services import youtube

router = APIRouter(
    tags=["Sources"]
)


def _claim(db: Session, source: SourceDB) -> None:
    """Take a failed source for processing, or refuse."""
    if not claim_failed_source(db, source.id):
        raise HTTPException(
            status_code=400,
            detail="Only a failed source can be retried"
        )
    db.refresh(source)


@router.post("/sources/{source_id}/retry", response_model=SourceResponse)
def retry_source(
    source: SourceDB = Depends(get_own_source),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Process a FAILED source again.

    An audio source is transcribed again from its stored file; a YouTube
    source is fetched again from YouTube.
    """
    if source.status != "FAILED":
        raise HTTPException(
            status_code=400,
            detail="Only a failed source can be retried"
        )

    if source.source_type == "AUDIO" and source.file_path:
        require_transcriber()

        if not os.path.isfile(to_disk_path(source.file_path)):
            raise HTTPException(
                status_code=400,
                detail="The stored file of this source is missing"
            )

        require_processing_slot(db, user.id)
        _claim(db, source)
        start_processing(db, source)
        return source

    if source.source_type == "YOUTUBE":
        video_id = youtube.parse_video_id(source.url or "")
        if video_id is None:
            raise HTTPException(
                status_code=400,
                detail="This source has no valid YouTube link"
            )

        if not worker.network.has_room():
            raise HTTPException(
                status_code=503,
                detail="The server is busy with other videos; try again later"
            )

        require_processing_slot(db, user.id)
        _claim(db, source)
        start_fetching(db, source, video_id)
        return source

    raise HTTPException(
        status_code=400,
        detail="This kind of source cannot be retried"
    )
