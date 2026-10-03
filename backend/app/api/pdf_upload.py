import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pypdf import PdfReader
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.api.source_chunks import save_chunks
from app.core.database import get_db
from app.models.project import ProjectDB
from app.models.source import SourceDB, SourceResponse, project_sources
from app.models.source_page import SourcePageDB
from app.services.quality_check import assess_extraction_quality
from app.services.text_cleaning import clean_extracted_text

router = APIRouter(
    tags=["PDF Upload"]
)

UPLOAD_DIR = "uploads/pdfs"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post(
    "/projects/{project_id}/sources/pdf",
    response_model=SourceResponse
)
async def upload_pdf(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    project = db.query(ProjectDB).filter(
        ProjectDB.id == project_id
    ).first()

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed"
        )

    unique_name = f"{uuid.uuid4()}.pdf"
    file_path = os.path.join(
        UPLOAD_DIR,
        unique_name
    )

    contents = await file.read()

    with open(file_path, "wb") as buffer:
        buffer.write(contents)

    try:
        reader = PdfReader(file_path)
        page_count = len(reader.pages)
    except Exception:
        if os.path.exists(file_path):
            os.remove(file_path)

        raise HTTPException(
            status_code=400,
            detail="Invalid PDF file"
        )

    source = SourceDB(
        title=file.filename,
        source_type="PDF",
        file_path=file_path,
        page_count=page_count,
        status="PROCESSING"
    )

    db.add(source)
    db.flush()

    db.execute(
        insert(project_sources).values(
            project_id=project_id,
            source_id=source.id
        )
    )

    try:
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

    except Exception:
        db.rollback()

        if os.path.exists(file_path):
            os.remove(file_path)

        raise HTTPException(
            status_code=500,
            detail="PDF text extraction failed"
        )

    return source
