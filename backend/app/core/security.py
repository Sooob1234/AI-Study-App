"""Password hashing and login tokens. No passwords are ever stored."""

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import ACCESS_TOKEN_DAYS, SECRET_KEY

# AUTH_V1

_ALGORITHM = "HS256"


def _prepare(password: str) -> bytes:
    # bcrypt only reads the first 72 bytes; hashing first lets a password
    # of any length count in full.
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("ascii"))
    except ValueError:
        return False


# Used when the email is unknown, so that a wrong email takes as long to
# answer as a wrong password.
DUMMY_HASH = hash_password("not-a-real-password")


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(days=ACCESS_TOKEN_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=_ALGORITHM)


def read_access_token(token: str) -> int | None:
    """Return the user id inside a valid token, otherwise None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
