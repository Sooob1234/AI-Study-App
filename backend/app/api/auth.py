from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.project import ProjectDB
from app.models.source import SourceDB
from app.models.user import TokenResponse, UserCreate, UserDB, UserResponse

router = APIRouter(
    prefix="/auth",
    tags=["Auth"]
)


def adopt_ownerless_rows(db: Session, user_id: int) -> None:
    """Give projects and sources that have no owner to a user.

    Rows made before accounts existed have no owner. They go to the first
    account, so that earlier work is not lost. Does not commit.
    """
    db.execute(
        update(ProjectDB)
        .where(ProjectDB.user_id.is_(None))
        .values(user_id=user_id)
    )
    db.execute(
        update(SourceDB)
        .where(SourceDB.user_id.is_(None))
        .values(user_id=user_id)
    )


@router.post("/register", response_model=UserResponse)
def register(
    data: UserCreate,
    db: Session = Depends(get_db)
):
    email = data.email.lower()

    if db.query(UserDB).filter(UserDB.email == email).first() is not None:
        raise HTTPException(
            status_code=409,
            detail="This email is already registered"
        )

    is_first_user = db.query(UserDB.id).first() is None

    user = UserDB(
        name=data.name,
        email=email,
        password_hash=hash_password(data.password),
    )
    db.add(user)

    try:
        db.flush()
    except IntegrityError:
        # Two registrations with the same email at the same moment.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This email is already registered"
        )

    if is_first_user:
        adopt_ownerless_rows(db, user.id)

    db.commit()
    db.refresh(user)

    return user


@router.post("/login", response_model=TokenResponse)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Log in. The "username" field takes the email address."""
    email = form.username.strip().lower()
    user = None

    # The database cannot even be asked about a text with a NUL character,
    # and no account has one in its email.
    if "\x00" not in email:
        user = db.query(UserDB).filter(UserDB.email == email).first()

    password_hash = user.password_hash if user is not None else DUMMY_HASH
    password_ok = verify_password(form.password, password_hash)

    if user is None or not password_ok:
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserResponse)
def me(user: UserDB = Depends(get_current_user)):
    return user
