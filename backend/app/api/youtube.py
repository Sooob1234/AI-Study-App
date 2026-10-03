import logging
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

logger = logging.getLogger(__name__)


class YouTubeSourceCreate(BaseModel):
    url: str = Field(max_length=2000)


def _fail(source_id: int, code: str) -> None:
    db = SessionLocal()
    try:
        source = db.query(SourceDB).filter(SourceDB.id == source_id).first()
        if source is not None:
            source.status = "FAILED"
            source.status_detail = code
            db.commit()
    finally:
        db.close()


def process_youtube_source(source_id: int, video_id: str) -> None:
    """Fetch and store the transcript of a YouTube source.

    Runs after the request has been answered. It always ends by setting
    the source to READY, NEEDS_REVIEW or FAILED.
    """
    # Step 1: fetch the captions. No database connection is held meanwhile.
    try:
        transcript = youtube.fetch_youtube(video_id)

        segments = []
        for start, end, text in transcript.segments:
            cleaned = clean_extracted_text(text)
            if cleaned:
                segments.append((start, end, cleaned))

        if not segments:
            raise youtube.YouTubeError(youtube.NO_TRANSCRIPT)

    except youtube.YouTubeError as error:
        _fail(source_id, error.code)
        return
    except Exception:
        logger.exception("Processing of YouTube source %s failed", source_id)
        _fail(source_id, youtube.FETCH_FAILED)
        return

    # Step 2: store the result.
    db = SessionLocal()
    try:
        source = db.query(SourceDB).filter(SourceDB.id == source_id).first()
        if source is None:
            # Deleted while it was being fetched.
            return

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
        if transcript.language:
            source.language = transcript.language[:10]
        source.duration = math.ceil(max(end for _, end, _ in segments))
        source.status, source.status_detail = assess_extraction_quality(
            [chunk.text for chunk in chunks]
        )

        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Storing the transcript of source %s failed", source_id)
        _fail(source_id, youtube.FETCH_FAILED)

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
