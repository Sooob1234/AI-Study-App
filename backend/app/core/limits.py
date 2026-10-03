"""Size limits of what the app accepts."""

MEGABYTE = 1024 * 1024

# Largest PDF accepted.
MAX_PDF_SIZE_MB = 50
MAX_PDF_SIZE_BYTES = MAX_PDF_SIZE_MB * MEGABYTE

# Largest audio file accepted, and the longest recording.
MAX_AUDIO_SIZE_MB = 200
MAX_AUDIO_SIZE_BYTES = MAX_AUDIO_SIZE_MB * MEGABYTE
MAX_AUDIO_HOURS = 4

# A YouTube source may be sent together with its transcript.
MAX_TRANSCRIPT_REQUEST_BYTES = 5 * MEGABYTE

# Every other request is a small piece of text.
MAX_ORDINARY_REQUEST_BYTES = MEGABYTE


def request_limit_for(path: str) -> int:
    """The largest request body, in bytes, that a path may receive.

    Uploads get a little room on top for the form around the file.
    """
    path = path.rstrip("/")

    if path.endswith("/sources/pdf"):
        return MAX_PDF_SIZE_BYTES + MEGABYTE
    if path.endswith("/sources/audio"):
        return MAX_AUDIO_SIZE_BYTES + MEGABYTE
    if path.endswith("/sources/youtube"):
        # May carry the transcript of a long video.
        return MAX_TRANSCRIPT_REQUEST_BYTES

    return MAX_ORDINARY_REQUEST_BYTES
