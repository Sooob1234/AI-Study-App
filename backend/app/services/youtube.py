"""Getting the transcript of a YouTube video.

Two parts:
- parse_video_id: pure text handling, fully covered by the tests.
- fetch_youtube: talks to YouTube over the network. It relies on captions
  that already exist for the video; a video without captions cannot be
  processed until speech-to-text is added.
"""

import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

# YOUTUBE_V1

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_PATH_PREFIXES = ("/shorts/", "/embed/", "/live/", "/v/")

# Reasons reported together with FAILED.
NO_TRANSCRIPT = "NO_TRANSCRIPT"
VIDEO_UNAVAILABLE = "VIDEO_UNAVAILABLE"
BLOCKED = "BLOCKED_BY_YOUTUBE"
FETCH_FAILED = "FETCH_FAILED"


class YouTubeError(Exception):
    """A video could not be processed; `code` says why."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class YouTubeTranscript:
    title: str | None
    language: str | None
    # (start_seconds, end_seconds, text), in order.
    segments: list[tuple[float, float, str]]


def parse_video_id(url: str) -> str | None:
    """Return the 11-character video id inside a YouTube link, or None."""
    url = (url or "").strip()
    if not url:
        return None

    if "://" not in url:
        url = "https://" + url

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None

    host = (parsed.hostname or "").lower()
    candidate = None

    if host in _SHORT_HOSTS:
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in _HOSTS:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        else:
            for prefix in _PATH_PREFIXES:
                if parsed.path.startswith(prefix):
                    candidate = parsed.path[len(prefix):].split("/")[0]
                    break

    if candidate and _VIDEO_ID.match(candidate):
        return candidate

    return None


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# Seconds to wait for YouTube before giving up, so that a source never
# stays PROCESSING for ever when YouTube cannot be reached.
REQUEST_TIMEOUT_SECONDS = 20


def _http_session():
    """A web session in which every request has a time limit."""
    import requests

    class TimeoutSession(requests.Session):
        def request(self, *args, **kwargs):
            kwargs.setdefault("timeout", REQUEST_TIMEOUT_SECONDS)
            return super().request(*args, **kwargs)

    session = TimeoutSession()

    proxies = _proxies()
    if proxies:
        session.proxies.update(proxies)

    return session


def _proxies() -> dict[str, str] | None:
    """The proxy to reach YouTube through, if YOUTUBE_PROXY_URL is set.

    YouTube refuses caption requests from most data-centre addresses. A
    server in a data centre therefore needs a proxy with a home-connection
    address (a "residential" proxy) to fetch captions itself.
    """
    url = (os.getenv("YOUTUBE_PROXY_URL") or "").strip()
    if not url:
        return None
    return {"http": url, "https": url}


def _fetch_title(video_id: str) -> str | None:
    """The video title from YouTube's public oEmbed service, if reachable."""
    try:
        response = _http_session().get(
            "https://www.youtube.com/oembed",
            params={"url": watch_url(video_id), "format": "json"},
        )
        if response.status_code == 200:
            return (response.json().get("title") or "").strip() or None
    except Exception:
        pass

    return None


def fetch_youtube(video_id: str) -> YouTubeTranscript:
    """Fetch the captions of a video. Raises YouTubeError when impossible."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api import _errors as errors

    try:
        # Captions written by a person come first in this list, then the
        # automatically generated ones. Any language is accepted.
        api = YouTubeTranscriptApi(http_client=_http_session())
        transcripts = list(api.list(video_id))
        if not transcripts:
            raise YouTubeError(NO_TRANSCRIPT)

        fetched = transcripts[0].fetch()

    except YouTubeError:
        raise
    except (errors.TranscriptsDisabled, errors.NoTranscriptFound):
        raise YouTubeError(NO_TRANSCRIPT)
    except (
        errors.VideoUnavailable,
        errors.VideoUnplayable,
        errors.InvalidVideoId,
        errors.AgeRestricted,
    ):
        raise YouTubeError(VIDEO_UNAVAILABLE)
    except (errors.RequestBlocked, errors.IpBlocked, errors.PoTokenRequired):
        raise YouTubeError(BLOCKED)
    except Exception:
        raise YouTubeError(FETCH_FAILED)

    segments = [
        (
            float(snippet.start),
            float(snippet.start) + float(snippet.duration),
            snippet.text,
        )
        for snippet in fetched.snippets
    ]

    return YouTubeTranscript(
        title=_fetch_title(video_id),
        language=fetched.language_code,
        segments=segments,
    )
