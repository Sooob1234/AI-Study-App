"""Settings read from the environment (the .env file)."""

import os
import secrets

from dotenv import load_dotenv

load_dotenv()

# Folder where uploaded files are stored.
UPLOAD_ROOT = os.getenv("UPLOAD_ROOT", "uploads")

# How long a login stays valid.
ACCESS_TOKEN_DAYS = int(os.getenv("ACCESS_TOKEN_DAYS", "30"))

_SECRET_FILE = ".secret_key"


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
        with open(_SECRET_FILE, encoding="utf-8") as handle:
            secret = handle.read().strip()
        if secret:
            return secret

    secret = secrets.token_urlsafe(48)
    with open(_SECRET_FILE, "w", encoding="utf-8") as handle:
        handle.write(secret)

    return secret


SECRET_KEY = _load_secret_key()
