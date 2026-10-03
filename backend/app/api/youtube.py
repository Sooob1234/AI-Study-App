import logging
import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_own_project
from app.api.source_chunks import save_chunks
from app.core import worker
from app.core.database import SessionLocal, get_db
from app.core.processing import (
    mark_failed,
    require_processing_slot,
    still_processing,
)
from app.models.project import ProjectDB
from app.models.source import SourceDB, SourceResponse, project_sources
from app.models.source_segment import SourceSegmentDB
from app.models.user import UserDB
from app.models.validation import clean_short_text
from app.services import youtube
from app.services.chunking import build_time_chunks
from app.services.quality_check import assess_extraction_quality
from app.services.text_cleaning import clean_extracted_text

router = APIRouter(
    tags=["YouTube"]
)

# YOUTUBE_API_V2

MAX_TITLE_CHARS = 255
# Limits of a transcript sent by the app itself.
MAX_SEGMENTS = 20000
MAX_SEGMENT_CHARS = 2000
MAX_VIDEO_SECONDS = 24 * 3600

logger = logging.getLogger(__name__)


class TranscriptSegmentIn(BaseModel):
    start: float = Field(ge=0, le=MAX_VIDEO_SECONDS)
    duration: float = Field(ge=0, le=3600)
    text: str = Field(max_length=MAX_SEGMENT_CHARS)


class YouTubeSourceCreate(BaseModel):
    url: str = Field(max_length=2000)

    # The three fields below are for the case where the app on the user's
    # own device has already read the captions. YouTube refuses caption
    # requests from most servers, but not from the device that plays the
    # video. When `segments` is given, the server does not contact YouTube.
    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)
    language: str | None = Field(
        default=None, max_length=10, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,6})?$"
    )
    segments: list[TranscriptSegmentIn] | None = Field(
        default=None, max_length=MAX_SEGMENTS
    )

    @field_validator("title")
    @classmethod
    def title_is_clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_short_text(value, "Title")


def _clean_segments(
    segments: list[tuple[float, float, str]]
) -> list[tuple[float, float, str]]:
    """Cleaned, non-empty transcript pieces in time order."""
    cleaned = []
    for start, end, text in segments:
        text = clean_extracted_text(text)
        if text:
            cleaned.append((start, max(start, end), text))

    cleaned.sort(key=lambda segment: segment[0])
    return cleaned


def _store_transcript(
    db: Session,
    source: SourceDB,
    segments: list[tuple[float, float, str]],
    title: str | None,
    language: str | None,
) -> None:
    """Save segments and chunks and set the final status. Does not commit."""
    db.execute(
        delete(SourceSegmentDB).where(SourceSegmentDB.source_id == source.id)
    )
    for index, (start, end, text) in enumerate(segments):
        db.add(SourceSegmentDB(
            source_id=source.id,
            segment_index=index,
            start_seconds=start,
            end_seconds=end,
            text=text,
        ))

    chunks = build_time_chunks(segments)
    save_chunks(db, source.id, chunks)

    if title:
        source.title = title[:MAX_TITLE_CHARS]
    if language:
        source.language = language[:10].lower()
    source.duration = math.ceil(max(end for _, end, _ in segments))
    source.status, source.status_detail = assess_extraction_quality(
        [chunk.text for chunk in chunks]
    )


def process_youtube_source(source_id: int, video_id: str) -> None:
    """Fetch and store the transcript of a YouTube source.

    Runs in the background worker. It always ends by setting the source to
    READY, NEEDS_REVIEW or FAILED.
    """
    try:
        _process_youtube_source(source_id, video_id)
    except Exception:
        logger.exception("Processing of YouTube source %s failed", source_id)
        mark_failed(source_id, youtube.FETCH_FAILED)


def _process_youtube_source(source_id: int, video_id: str) -> None:
    # Step 1: fetch the captions. No database connection is held meanwhile.
    try:
        transcript = youtube.fetch_youtube(video_id)
        segments = _clean_segments(transcript.segments)

        if not segments:
            raise youtube.YouTubeError(youtube.NO_TRANSCRIPT)

    except youtube.YouTubeError as error:
        mark_failed(source_id, error.code)
        return

    # Step 2: store the result, unless the source was deleted or finished
    # by something else in the meantime.
    db = SessionLocal()
    try:
        source = still_processing(db, source_id)
        if source is None:
            return

        _store_transcript(
            db, source, segments, transcript.title, transcript.language
        )
        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def start_fetching(db: Session, source: SourceDB, video_id: str) -> None:
    """Hand a YouTube source to the background worker."""
    try:
        worker.network.submit(process_youtube_source, source.id, video_id)
    except worker.WorkerBusy:
        mark_failed(source.id, youtube.SERVER_BUSY)
        db.refresh(source)


@router.post(
    "/projects/{project_id}/sources/youtube",
    response_model=SourceResponse
)
def add_youtube_source(
    data: YouTubeSourceCreate,
    project: ProjectDB = Depends(get_own_project),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a YouTube video.

    With only `url`: the server fetches the captions itself. The answer
    comes back at once with status PROCESSING; ask GET /sources/{id} to see
    when it is READY.

    With `segments` as well: the captions were already read on the user's
    device, the server does not contact YouTube, and the answer already
    carries the final status.
    """
    video_id = youtube.parse_video_id(data.url)

    if video_id is None:
        raise HTTPException(
            status_code=400,
            detail="Not a valid YouTube video link"
        )

    segments = None
    if data.segments is not None:
        segments = _clean_segments([
            (item.start, item.start + item.duration, item.text)
            for item in data.segments
        ])
        if not segments:
            raise HTTPException(
                status_code=400,
                detail="The transcript is empty"
            )

    if segments is None:
        require_processing_slot(db, user.id)
        if not worker.network.has_room():
            raise HTTPException(
                status_code=503,
                detail="The server is busy with other videos; try again later"
            )

    source = SourceDB(
        user_id=user.id,
        title=data.title or f"YouTube video {video_id}",
        source_type="YOUTUBE",
        url=youtube.watch_url(video_id),
        language=data.language.lower() if data.language else None,
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

    if segments is not None:
        _store_transcript(db, source, segments, None, None)

    db.commit()
    db.refresh(source)

    if segments is None:
        start_fetching(db, source, video_id)

    return source
