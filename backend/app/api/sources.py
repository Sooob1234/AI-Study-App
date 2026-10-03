import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_own_project, get_own_source
from app.core.config import UPLOAD_ROOT, to_disk_path
from app.core.database import get_db
from app.models.project import ProjectDB
from app.models.source import (
    SourceDB,
    SourceResponse,
    project_sources,
)

router = APIRouter(
    tags=["Sources"]
)


@router.get(
    "/projects/{project_id}/sources/",
    response_model=list[SourceResponse]
)
def get_project_sources(
    project: ProjectDB = Depends(get_own_project),
    db: Session = Depends(get_db)
):
    statement = (
        select(SourceDB)
        .join(
            project_sources,
            SourceDB.id == project_sources.c.source_id
        )
        .where(
            project_sources.c.project_id == project.id
        )
        .order_by(SourceDB.id.desc())
    )

    return db.scalars(statement).all()


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(source: SourceDB = Depends(get_own_source)):
    """One source: its type, size and processing status."""
    return source


# DELETE_SOURCE_V1


def _remove_stored_file(file_path: str | None) -> bool:
    """Remove a source's stored file. Returns True if a file was removed."""
    if not file_path:
        return False

    root = os.path.realpath(UPLOAD_ROOT)
    target = os.path.realpath(to_disk_path(file_path))

    # Never touch anything outside the uploads folder.
    if os.path.commonpath([root, target]) != root:
        return False

    if not os.path.isfile(target):
        return False

    os.remove(target)
    return True


@router.delete("/sources/{source_id}")
def delete_source(
    source: SourceDB = Depends(get_own_source),
    db: Session = Depends(get_db)
):
    """Delete a source completely: its pages, chunks, project links and file."""
    source_id = source.id
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
