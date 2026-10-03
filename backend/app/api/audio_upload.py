import logging
import os
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_own_project
from app.api.source_chunks import save_chunks
from app.core import worker
from app.core.config import UPLOAD_ROOT, to_disk_path, to_stored_path
from app.core.database import SessionLocal, get_db
from app.core.processing import (
    mark_failed,
    require_processing_slot,
    still_processing,
)
from app.core.limits import MAX_AUDIO_HOURS, MAX_AUDIO_SIZE_BYTES, MAX_AUDIO_SIZE_MB
from app.models.project import ProjectDB
from app.models.source import SourceDB, SourceResponse, project_sources
from app.models.source_segment import SourceSegmentDB
from app.models.user import UserDB
from app.models.validation import title_from_filename
from app.services import transcription
from app.services.chunking import build_time_chunks
from app.services.quality_check import assess_extraction_quality
from app.services.text_cleaning import clean_extracted_text

router = APIRouter(
    tags=["Audio Upload"]
)

# AUDIO_UPLOAD_V1

logger = logging.getLogger(__name__)

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

    Runs in the background worker. It always ends by setting the source to
    READY, NEEDS_REVIEW or FAILED.
    """
    try:
        _process_audio_source(source_id)
    except Exception:
        logger.exception("Processing of audio source %s failed", source_id)
        mark_failed(source_id, transcription.TRANSCRIPTION_FAILED)


def _process_audio_source(source_id: int) -> None:
    # Step 1: look up what to transcribe, and let go of the database. The
    # recognition can take minutes and must not keep a connection open.
    db = SessionLocal()
    try:
        source = db.query(SourceDB).filter(
            SourceDB.id == source_id,
            SourceDB.status == "PROCESSING"
        ).first()
        if source is None or not source.file_path:
            # Deleted, or already finished, before processing started.
            return
        disk_path = to_disk_path(source.file_path)
        language = source.language
    finally:
        db.close()

    # Step 2: measure the real length, then recognise the speech.
    try:
        duration = transcription.measure_audio(
            disk_path, MAX_AUDIO_HOURS * 3600
        )
        transcript = transcription.transcribe(disk_path, language=language)

        segments = []
        for start, end, text in transcript.segments:
            cleaned = clean_extracted_text(text)
            if cleaned:
                segments.append((start, end, cleaned))

        if not segments:
            raise transcription.TranscriptionError(transcription.NO_SPEECH)

    except transcription.TranscriptionError as error:
        mark_failed(source_id, error.code)
        return
    except transcription.AudioError:
        mark_failed(source_id, transcription.TRANSCRIPTION_FAILED)
        return

    # Step 3: store the result, unless the source was deleted or finished
    # by something else in the meantime.
    db = SessionLocal()
    try:
        source = still_processing(db, source_id)
        if source is None:
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

        source.duration = max(1, round(duration))
        if not source.language and transcript.language:
            source.language = transcript.language[:10]
        source.status, source.status_detail = assess_extraction_quality(
            [chunk.text for chunk in chunks]
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def require_transcriber() -> None:
    if not transcription.is_available():
        raise HTTPException(
            status_code=503,
            detail="Audio processing is not installed on this server"
        )

    if not worker.speech.has_room():
        raise HTTPException(
            status_code=503,
            detail="The server is busy with other audio files; try again later"
        )


def start_processing(db: Session, source: SourceDB) -> None:
    """Hand a source to the background worker."""
    try:
        worker.speech.submit(process_audio_source, source.id)
    except worker.WorkerBusy:
        mark_failed(source.id, transcription.SERVER_BUSY)
        db.refresh(source)


@router.post(
    "/projects/{project_id}/sources/audio",
    response_model=SourceResponse
)
def upload_audio(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    project: ProjectDB = Depends(get_own_project),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload an audio file. The answer comes back at once with status
    PROCESSING; ask GET /sources/{id} to see when it is READY.

    `language` is the language spoken in the recording, as a code such as
    "fa" or "en". It is optional, but giving it avoids a wrong guess.
    """
    require_transcriber()
    require_processing_slot(db, user.id)

    language = (language or "").strip().lower() or None
    if language is not None and language not in transcription.supported_languages():
        raise HTTPException(
            status_code=400,
            detail="Unknown language code"
        )

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
            title=title_from_filename(filename, MAX_TITLE_CHARS),
            source_type="AUDIO",
            language=language,
            file_path=to_stored_path(file_path),
            duration=max(1, round(duration)),
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

    start_processing(db, source)

    return source
