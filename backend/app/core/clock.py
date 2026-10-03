from datetime import datetime, timezone


def utc_now() -> datetime:
    """The current time in UTC, in the form the database columns store."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
