from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_own_project
from app.core.database import get_db
from app.models.project import ProjectCreate, ProjectDB, ProjectResponse
from app.models.user import UserDB

router = APIRouter(
    prefix="/projects",
    tags=["Projects"]
)


@router.get("/", response_model=list[ProjectResponse])
def get_projects(
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(ProjectDB).filter(
        ProjectDB.user_id == user.id
    ).order_by(ProjectDB.id.desc()).all()


@router.post("/", response_model=ProjectResponse)
def create_project(
    data: ProjectCreate,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = ProjectDB(user_id=user.id, title=data.title)

    db.add(project)
    db.commit()
    db.refresh(project)

    return project


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project: ProjectDB = Depends(get_own_project)):
    return project
