"""Shared checks used by the endpoints: who is asking, and is it theirs?"""

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import read_access_token
from app.models.project import ProjectDB
from app.models.source import SourceDB
from app.models.user import UserDB

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> UserDB:
    user_id = read_access_token(token)
    user = None

    if user_id is not None:
        user = db.query(UserDB).filter(UserDB.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Not logged in",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# Something that belongs to another user is reported as "not found", so
# that nobody can learn which ids exist.

def get_own_project(
    project_id: int,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> ProjectDB:
    project = db.query(ProjectDB).filter(
        ProjectDB.id == project_id,
        ProjectDB.user_id == user.id
    ).first()

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    return project


def get_own_source(
    source_id: int,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> SourceDB:
    source = db.query(SourceDB).filter(
        SourceDB.id == source_id,
        SourceDB.user_id == user.id
    ).first()

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Source not found"
        )

    return source
