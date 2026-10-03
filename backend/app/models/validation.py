"""Rules shared by the texts that users send."""

import re

# The largest whole number a database id or counter can hold.
MAX_DB_INTEGER = 2_147_483_647

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def clean_short_text(value: str, what: str) -> str:
    """A one-line text: trimmed, not empty, no invisible control characters."""
    if _CONTROL_CHARS.search(value):
        raise ValueError(f"{what} must not contain control characters")

    value = value.strip()
    if not value:
        raise ValueError(f"{what} must not be empty")

    return value


def title_from_filename(filename: str, max_chars: int = 255) -> str:
    """A storable title made from the name of an uploaded file."""
    title = _CONTROL_CHARS.sub("", filename).strip()
    return title[:max_chars] or "Untitled"
