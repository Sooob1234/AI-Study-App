import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pypdf import PdfReader
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_own_project
from app.api.source_chunks import save_chunks
from app.core.config import UPLOAD_ROOT
from app.core.database import get_db
from app.models.project import ProjectDB
from app.models.user import UserDB
from app.models.source import SourceDB, SourceResponse, project_sources
from app.models.source_page import SourcePageDB
from app.services.quality_check import assess_extraction_quality
from app.services.text_cleaning import clean_extracted_text

router = APIRouter(
    tags=["PDF Upload"]
)

# UPLOAD_HARDENING_V1

UPLOAD_DIR = os.path.join(UPLOAD_ROOT, "pdfs")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Largest PDF accepted, in megabytes.
MAX_PDF_SIZE_MB = 50
MAX_PDF_SIZE_BYTES = MAX_PDF_SIZE_MB * 1024 * 1024
# The title column holds at most this many characters.
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
            if size > MAX_PDF_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF is larger than {MAX_PDF_SIZE_MB} MB"
                )

            buffer.write(block)


# A plain "def" (not "async def"): FastAPI then runs this slow work in a
# separate worker thread, so other requests are not kept waiting.
@router.post(
    "/projects/{project_id}/sources/pdf",
    response_model=SourceResponse
)
def upload_pdf(
    file: UploadFile = File(...),
    project: ProjectDB = Depends(get_own_project),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    filename = (file.filename or "").strip()

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed"
        )

    file_path = os.path.join(
        UPLOAD_DIR,
        f"{uuid.uuid4()}.pdf"
    )

    # From here on, any failure must also remove the stored file.
    try:
        _store_upload(file, file_path)

        try:
            reader = PdfReader(file_path)
            encrypted = reader.is_encrypted
            page_count = 0 if encrypted else len(reader.pages)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid PDF file"
            )

        if encrypted:
            raise HTTPException(
                status_code=400,
                detail="Password-protected PDF files are not supported"
            )

        source = SourceDB(
            user_id=user.id,
            title=filename[:MAX_TITLE_CHARS],
            source_type="PDF",
            file_path=file_path,
            page_count=page_count,
            status="PROCESSING"
        )

        db.add(source)
        db.flush()

        db.execute(
            insert(project_sources).values(
                project_id=project.id,
                source_id=source.id
            )
        )

        page_texts = []

        for index, page in enumerate(reader.pages):
            extracted_text = page.extract_text() or ""
            cleaned_text = clean_extracted_text(extracted_text)
            page_texts.append(cleaned_text)

            page_record = SourcePageDB(
                source_id=source.id,
                page_number=index + 1,
                text=cleaned_text
            )

            db.add(page_record)

        # Split the text into chunks that keep their page numbers and heading.
        save_chunks(
            db,
            source.id,
            [(index + 1, text) for index, text in enumerate(page_texts)]
        )

        # READY only if the extracted text is usable; an empty or broken
        # text makes the source NEEDS_REVIEW instead.
        source.status = assess_extraction_quality(page_texts)

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
            detail="PDF text extraction failed"
        )

    return source
