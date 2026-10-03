import math
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_own_project, get_own_source
from app.api.source_chunks import save_chunks
from app.core.config import UPLOAD_ROOT, to_disk_path, to_stored_path
from app.core.database import SessionLocal, get_db
from app.core.limits import MAX_AUDIO_HOURS, MAX_AUDIO_SIZE_BYTES, MAX_AUDIO_SIZE_MB
from app.models.project import ProjectDB
from app.models.source import SourceDB, SourceResponse, project_sources
from app.models.source_segment import SourceSegmentDB
from app.models.user import UserDB
from app.services import transcription
from app.services.chunking import build_time_chunks
from app.services.quality_check import assess_extraction_quality
from app.services.text_cleaning import clean_extracted_text

router = APIRouter(
    tags=["Audio Upload"]
)

# AUDIO_UPLOAD_V1

AUDIO_DIR = os.path.join(UPLOAD_ROOT, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".mp3", ".m4a", ".wav", ".ogg", ".oga", ".opus", ".flac", ".aac",
    ".wma", ".webm", ".mp4",
}
MAX_TITLE_CHARS = 255
_READ_BLOCK_BYTES = 1024 * 1024


def _remove_file(file_path: str) -> None:
    if os.path.exists(file_path):
        os.remove(file_path)


def _store_upload(file: UploadFile, file_path: str) -> None:
    """Write the upload to disk block by block, stopping at the size limit."""
    size = 0

    with open(file_path, "wb") as buffer:
        while True:
            block = file.file.read(_READ_BLOCK_BYTES)
            if not block:
                break

            size += len(block)
            if size > MAX_AUDIO_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Audio file is larger than {MAX_AUDIO_SIZE_MB} MB"
                )

            buffer.write(block)


def process_audio_source(source_id: int) -> None:
    """Transcribe and store an audio source.

    Runs after the request has been answered. It always ends by setting
    the source to READY, NEEDS_REVIEW or FAILED.
    """
    db = SessionLocal()

    try:
        source = db.query(SourceDB).filter(SourceDB.id == source_id).first()
        if source is None or not source.file_path:
            # Deleted before processing started.
            return

        try:
            transcript = transcription.transcribe(
                to_disk_path(source.file_path)
            )

            segments = []
            for start, end, text in transcript.segments:
                cleaned = clean_extracted_text(text)
                if cleaned:
                    segments.append((start, end, cleaned))

            if not segments:
                raise transcription.TranscriptionError(transcription.NO_SPEECH)

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

            source.status, source.status_detail = assess_extraction_quality(
                [chunk.text for chunk in chunks]
            )

            db.commit()

        except Exception as error:
            db.rollback()

            code = transcription.TRANSCRIPTION_FAILED
            if isinstance(error, transcription.TranscriptionError):
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


def _require_transcriber() -> None:
    if not transcription.is_available():
        raise HTTPException(
            status_code=503,
            detail="Audio processing is not installed on this server"
        )


@router.post(
    "/projects/{project_id}/sources/audio",
    response_model=SourceResponse
)
def upload_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project: ProjectDB = Depends(get_own_project),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload an audio file. The answer comes back at once with status
    PROCESSING; ask GET /sources/{id} to see when it is READY."""
    _require_transcriber()

    filename = (file.filename or "").strip()
    extension = os.path.splitext(filename)[1].lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="This kind of audio file is not supported"
        )

    file_path = os.path.join(AUDIO_DIR, f"{uuid.uuid4()}{extension}")

    # From here on, any failure must also remove the stored file.
    try:
        _store_upload(file, file_path)

        try:
            duration = transcription.probe_audio(file_path)
        except transcription.AudioError:
            raise HTTPException(
                status_code=400,
                detail="Invalid audio file"
            )

        if duration > MAX_AUDIO_HOURS * 3600:
            raise HTTPException(
                status_code=400,
                detail=f"Audio is longer than {MAX_AUDIO_HOURS} hours"
            )

        source = SourceDB(
            user_id=user.id,
            title=filename[:MAX_TITLE_CHARS],
            source_type="AUDIO",
            file_path=to_stored_path(file_path),
            duration=math.ceil(duration),
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

    except HTTPException:
        db.rollback()
        _remove_file(file_path)
        raise

    except Exception:
        db.rollback()
        _remove_file(file_path)

        raise HTTPException(
            status_code=500,
            detail="Audio upload failed"
        )

    background_tasks.add_task(process_audio_source, source.id)

    return source


@router.post("/sources/{source_id}/retry", response_model=SourceResponse)
def retry_source(
    background_tasks: BackgroundTasks,
    source: SourceDB = Depends(get_own_source),
    db: Session = Depends(get_db)
):
    """Process a FAILED audio source again, from the file already stored."""
    if source.source_type != "AUDIO" or not source.file_path:
        raise HTTPException(
            status_code=400,
            detail="Only audio sources can be retried"
        )

    if source.status != "FAILED":
        raise HTTPException(
            status_code=400,
            detail="Only a failed source can be retried"
        )

    _require_transcriber()

    if not os.path.isfile(to_disk_path(source.file_path)):
        raise HTTPException(
            status_code=400,
            detail="The stored file of this source is missing"
        )

    source.status = "PROCESSING"
    source.status_detail = None
    db.commit()
    db.refresh(source)

    background_tasks.add_task(process_audio_source, source.id)

    return source
