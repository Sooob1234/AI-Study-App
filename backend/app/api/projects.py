from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.project import ProjectCreate, ProjectDB, ProjectResponse

router = APIRouter(
    prefix="/projects",
    tags=["Projects"]
)


@router.get("/", response_model=list[ProjectResponse])
def get_projects(db: Session = Depends(get_db)):
    return db.query(ProjectDB).order_by(ProjectDB.id.desc()).all()


@router.post("/", response_model=ProjectResponse)
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db)
):
    project = ProjectDB(title=data.title)

    db.add(project)
    db.commit()
    db.refresh(project)

    return project


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
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

    return project
