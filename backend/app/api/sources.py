from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import insert, select
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

    source = SourceDB(
        title=data.title,
        source_type=data.source_type.value,
        url=data.url,
        file_path=data.file_path,
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
