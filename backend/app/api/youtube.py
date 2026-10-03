import math

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_own_project
from app.api.source_chunks import save_chunks
from app.core.database import SessionLocal, get_db
from app.models.project import ProjectDB
from app.models.source import SourceDB, SourceResponse, project_sources
from app.models.source_segment import SourceSegmentDB
from app.models.user import UserDB
from app.services import youtube
from app.services.chunking import build_time_chunks
from app.services.quality_check import assess_extraction_quality
from app.services.text_cleaning import clean_extracted_text

router = APIRouter(
    tags=["YouTube"]
)

MAX_TITLE_CHARS = 255


class YouTubeSourceCreate(BaseModel):
    url: str = Field(max_length=2000)


def process_youtube_source(source_id: int, video_id: str) -> None:
    """Fetch and store the transcript of a YouTube source.

    Runs after the request has been answered. It always ends by setting
    the source to READY, NEEDS_REVIEW or FAILED.
    """
    db = SessionLocal()

    try:
        source = db.query(SourceDB).filter(SourceDB.id == source_id).first()
        if source is None:
            # Deleted before processing started.
            return

        try:
            transcript = youtube.fetch_youtube(video_id)

            segments = []
            for start, end, text in transcript.segments:
                cleaned = clean_extracted_text(text)
                if cleaned:
                    segments.append((start, end, cleaned))

            if not segments:
                raise youtube.YouTubeError(youtube.NO_TRANSCRIPT)

            db.execute(
                delete(SourceSegmentDB).where(
                    SourceSegmentDB.source_id == source_id
                )
            )
            for index, (start, end, text) in enumerate(segments):
                db.add(SourceSegmentDB(
                    source_id=source_id,
                    segment_index=index,
                    start_seconds=start,
                    end_seconds=end,
                    text=text,
                ))

            chunks = build_time_chunks(segments)
            save_chunks(db, source_id, chunks)

            if transcript.title:
                source.title = transcript.title[:MAX_TITLE_CHARS]
            source.duration = math.ceil(max(end for _, end, _ in segments))
            source.status, source.status_detail = assess_extraction_quality(
                [chunk.text for chunk in chunks]
            )

            db.commit()

        except Exception as error:
            db.rollback()

            code = youtube.FETCH_FAILED
            if isinstance(error, youtube.YouTubeError):
                code = error.code

            source = db.query(SourceDB).filter(
                SourceDB.id == source_id
            ).first()
            if source is not None:
                source.status = "FAILED"
                source.status_detail = code
                db.commit()

    finally:
        db.close()


def fail_interrupted_sources() -> int:
    """Mark YouTube sources that were cut off by a restart as FAILED.

    Processing runs inside the app itself, so a source still PROCESSING
    when the app starts can never finish. Returns how many were marked.
    """
    db = SessionLocal()

    try:
        count = db.query(SourceDB).filter(
            SourceDB.source_type == "YOUTUBE",
            SourceDB.status == "PROCESSING"
        ).update({
            "status": "FAILED",
            "status_detail": youtube.INTERRUPTED,
        })
        db.commit()
        return count
    finally:
        db.close()


@router.post(
    "/projects/{project_id}/sources/youtube",
    response_model=SourceResponse
)
def add_youtube_source(
    data: YouTubeSourceCreate,
    background_tasks: BackgroundTasks,
    project: ProjectDB = Depends(get_own_project),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a YouTube video. The answer comes back at once with status
    PROCESSING; ask GET /sources/{id} to see when it is READY."""
    video_id = youtube.parse_video_id(data.url)

    if video_id is None:
        raise HTTPException(
            status_code=400,
            detail="Not a valid YouTube video link"
        )

    source = SourceDB(
        user_id=user.id,
        title=f"YouTube video {video_id}",
        source_type="YOUTUBE",
        url=youtube.watch_url(video_id),
        status="PROCESSING",
    )

    db.add(source)
    db.flush()

    db.execute(
        insert(project_sources).values(
            project_id=project.id,
            source_id=source.id
        )
    )

    db.commit()
    db.refresh(source)

    background_tasks.add_task(process_youtube_source, source.id, video_id)

    return source
