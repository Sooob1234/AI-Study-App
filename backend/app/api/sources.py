import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.project import ProjectDB
from app.models.source import (
    SourceCreate,
    SourceDB,
    SourceResponse,
    project_sources,
)

router = APIRouter(
    tags=["Sources"]
)


@router.post(
    "/projects/{project_id}/sources/",
    response_model=SourceResponse
)
def create_source(
    project_id: int,
    data: SourceCreate,
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

    if data.source_type.value == "PDF":
        raise HTTPException(
            status_code=400,
            detail="PDF sources are added with the PDF upload endpoint"
        )

    source = SourceDB(
        title=data.title,
        source_type=data.source_type.value,
        url=data.url,
        file_path=None,
        duration=data.duration,
        page_count=data.page_count,
        status="PROCESSING",
    )

    db.add(source)
    db.flush()

    db.execute(
        insert(project_sources).values(
            project_id=project_id,
            source_id=source.id
        )
    )

    db.commit()
    db.refresh(source)

    return source


@router.get(
    "/projects/{project_id}/sources/",
    response_model=list[SourceResponse]
)
def get_project_sources(
    project_id: int,
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

    statement = (
        select(SourceDB)
        .join(
            project_sources,
            SourceDB.id == project_sources.c.source_id
        )
        .where(
            project_sources.c.project_id == project_id
        )
        .order_by(SourceDB.id.desc())
    )

    return db.scalars(statement).all()


# DELETE_SOURCE_V1

# Only files inside this folder may be removed from disk.
UPLOAD_ROOT = "uploads"


def _remove_stored_file(file_path: str | None) -> bool:
    """Remove a source's stored file. Returns True if a file was removed."""
    if not file_path:
        return False

    root = os.path.realpath(UPLOAD_ROOT)
    target = os.path.realpath(file_path)

    # Never touch anything outside the uploads folder.
    if os.path.commonpath([root, target]) != root:
        return False

    if not os.path.isfile(target):
        return False

    os.remove(target)
    return True


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: int,
    db: Session = Depends(get_db)
):
    """Delete a source completely: its pages, chunks, project links and file."""
    source = db.query(SourceDB).filter(
        SourceDB.id == source_id
    ).first()

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Source not found"
        )

    title = source.title
    file_path = source.file_path

    # Pages, chunks and project links go with it (database cascade).
    db.execute(
        delete(SourceDB).where(SourceDB.id == source_id)
    )
    db.commit()

    # The file is removed only after the database change has succeeded.
    try:
        file_removed = _remove_stored_file(file_path)
    except OSError:
        file_removed = False

    return {
        "deleted_source_id": source_id,
        "title": title,
        "file_removed": file_removed,
    }
