import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.audio_upload import require_transcriber, start_processing
from app.api.deps import get_own_source
from app.api.youtube import process_youtube_source
from app.core.config import to_disk_path
from app.core.database import get_db
from app.models.source import SourceDB, SourceResponse
from app.services import youtube

router = APIRouter(
    tags=["Sources"]
)


@router.post("/sources/{source_id}/retry", response_model=SourceResponse)
def retry_source(
    background_tasks: BackgroundTasks,
    source: SourceDB = Depends(get_own_source),
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

        source.status = "PROCESSING"
        source.status_detail = None
        db.commit()
        db.refresh(source)

        start_processing(db, source)
        return source

    if source.source_type == "YOUTUBE":
        video_id = youtube.parse_video_id(source.url or "")
        if video_id is None:
            raise HTTPException(
                status_code=400,
                detail="This source has no valid YouTube link"
            )

        source.status = "PROCESSING"
        source.status_detail = None
        db.commit()
        db.refresh(source)

        background_tasks.add_task(process_youtube_source, source.id, video_id)
        return source

    raise HTTPException(
        status_code=400,
        detail="This kind of source cannot be retried"
    )
