"""Checks made on an upload before any of its body is read.

FastAPI receives the whole upload first and only then runs the endpoint's
own checks. For large uploads that is too late: an anonymous visitor could
make the server receive hundreds of megabytes. These checks need nothing
but the request's address and headers, so they run first.
"""

from app.core import worker
from app.core.security import read_access_token
from app.services import transcription

_UPLOAD_SUFFIXES = ("/sources/pdf", "/sources/audio")


def _bearer_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                return token.strip()
    return None


def refuse_before_reading(scope) -> tuple[int, str] | None:
    """Return (status, message) to refuse an upload unread, or None."""
    if scope.get("method") != "POST":
        return None

    path = scope.get("path", "").rstrip("/")
    if not path.endswith(_UPLOAD_SUFFIXES):
        return None

    token = _bearer_token(scope.get("headers", []))
    if token is None or read_access_token(token) is None:
        return 401, "Not logged in"

    if path.endswith("/sources/audio"):
        if not transcription.is_available():
            return 503, "Audio processing is not installed on this server"
        if not worker.speech.has_room():
            return 503, "The server is busy with other audio files; try again later"

    return None
