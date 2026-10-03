"""Settings read from the environment (the .env file)."""

import os
import secrets

from dotenv import load_dotenv

load_dotenv()

# The "backend" folder. Paths below are tied to it, so the app behaves the
# same no matter which folder it is started from.
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# Folder where uploaded files are stored.
UPLOAD_ROOT = os.path.abspath(
    os.path.join(BASE_DIR, os.getenv("UPLOAD_ROOT") or "uploads")
)

# How long a login stays valid.
ACCESS_TOKEN_DAYS = int(os.getenv("ACCESS_TOKEN_DAYS", "30"))

_SECRET_FILE = os.path.join(BASE_DIR, ".secret_key")


def to_stored_path(disk_path: str) -> str:
    """The form in which a file's location is kept in the database."""
    disk_path = os.path.abspath(disk_path)
    if os.path.commonpath([BASE_DIR, disk_path]) == BASE_DIR:
        return os.path.relpath(disk_path, BASE_DIR).replace(os.sep, "/")
    return disk_path


def to_disk_path(stored_path: str) -> str:
    """The real location on disk of a path kept in the database."""
    return os.path.abspath(os.path.join(BASE_DIR, stored_path))


def _load_secret_key() -> str:
    """The key that signs login tokens.

    Taken from JWT_SECRET if set. Otherwise a random key is created once and
    kept in a local file that is never published, so that logins survive a
    restart of the app.
    """
    secret = os.getenv("JWT_SECRET")
    if secret:
        return secret

    if os.path.exists(_SECRET_FILE):
        try:
            # Readable by the owner of the file only.
            os.chmod(_SECRET_FILE, 0o600)
        except OSError:
            pass

        with open(_SECRET_FILE, encoding="utf-8") as handle:
            secret = handle.read().strip()
        if secret:
            return secret

    secret = secrets.token_urlsafe(48)
    # Readable by the owner of the file only.
    descriptor = os.open(_SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secret)

    return secret


SECRET_KEY = _load_secret_key()
