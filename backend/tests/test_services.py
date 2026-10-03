"""Checks for the source-processing services. They need no database.

Run from the backend folder:  python -m pytest
"""

from app.services.chunking import (
    HEADING_SEPARATOR,
    MAX_CHUNK_CHARS,
    build_chunks,
    build_time_chunks,
)
from app.services.quality_check import assess_extraction_quality
from app.services.text_cleaning import clean_extracted_text
from app.services import youtube
from app.services.youtube import parse_video_id


# --- text cleaning ---------------------------------------------------------

def test_arabic_letters_become_persian():
    assert clean_extracted_text("كتاب عربي") == "کتاب عربی"


def test_mirrored_brackets_are_fixed():
    assert clean_extracted_text(")الف( و )ب(") == "(الف) و (ب)"
    assert clean_extracted_text("»نقل«") == "«نقل»"


def test_correct_brackets_are_left_alone():
    assert clean_extracted_text("(a) and (b)") == "(a) and (b)"


def test_list_markers_survive_bracket_fix():
    cleaned = clean_extracted_text("1) یک\n2) دو\n)سه( و )چهار(")
    assert cleaned == "1) یک\n2) دو\n(سه) و (چهار)"


def test_control_characters_are_removed():
    assert clean_extracted_text("a\x00b\x07c\nd") == "abc\nd"


def test_empty_input():
    assert clean_extracted_text(None) == ""
    assert clean_extracted_text("   ") == ""


# --- quality check ---------------------------------------------------------

GOOD = "این متن از یک جزوه است که در آن هر جمله با دقت نوشته شده است. " * 5
REVERSED = "نیا نتم زا کی هوزج تسا هک رد نآ ره هلمج اب تقد هتشون هدش تسا. " * 5


def test_good_text_is_ready():
    assert assess_extraction_quality([GOOD, GOOD]) == ("READY", None)


def test_reversed_text_needs_review():
    assert assess_extraction_quality([REVERSED, REVERSED]) == (
        "NEEDS_REVIEW", "REVERSED_TEXT"
    )


def test_empty_pages_need_review():
    assert assess_extraction_quality(["", ""]) == ("NEEDS_REVIEW", "NO_TEXT")
    assert assess_extraction_quality([]) == ("NEEDS_REVIEW", "NO_TEXT")


def test_english_text_is_ready():
    assert assess_extraction_quality(["A page of plain English text."]) == (
        "READY", None
    )


# --- chunking --------------------------------------------------------------

def _pages():
    def body(name):
        return "\n".join(f"سطر {i} از متن {name}" for i in range(12))

    return [
        (1, f"1 سرصفحه جزوه\n1- فصل اول\n{body('الف')}"),
        (2, f"2 سرصفحه جزوه\n2- فصل دوم\n2 -1 - بخش یک\n{body('ب')}"),
        (3, f"3 سرصفحه جزوه\n{body('پ')}\n2 -2- بخش دو\n{body('ت')}"),
    ]


def test_chunks_follow_headings_and_pages():
    chunks = build_chunks(_pages())
    headings = [chunk.heading for chunk in chunks]

    assert headings[0] == "1- فصل اول"
    assert "2- فصل دوم" + HEADING_SEPARATOR + "2 -1 - بخش یک" in headings
    assert "2- فصل دوم" + HEADING_SEPARATOR + "2 -2- بخش دو" in headings
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))

    section = next(c for c in chunks if c.heading.endswith("بخش یک"))
    assert (section.page_start, section.page_end) == (2, 3)


def test_running_header_is_removed_and_nothing_else_is_lost():
    pages = _pages()
    chunks = build_chunks(pages)
    chunk_lines = [line for c in chunks for line in c.text.split("\n")]
    page_lines = [
        line for _, text in pages for line in text.split("\n")[1:]
    ]

    assert chunk_lines == page_lines
    assert not any("سرصفحه" in line for line in chunk_lines)


def test_no_chunk_is_a_bare_heading():
    for chunk in build_chunks(_pages()):
        assert len(chunk.text.split("\n")) > 1


def test_long_section_is_split():
    text = "\n".join("جمله ای نسبتا بلند برای پر کردن متن این صفحه. " * 2 for _ in range(60))
    chunks = build_chunks([(1, text)])
    assert len(chunks) > 1
    assert all(chunk.heading is None for chunk in chunks)


def test_pages_without_text_give_no_chunks():
    assert build_chunks([(1, ""), (2, "")]) == []


def test_time_chunks_keep_their_time_span():
    segments = [(i * 4.0, i * 4.0 + 4.0, f"spoken words number {i} " * 6) for i in range(40)]
    chunks = build_time_chunks(segments + [(160.0, 161.0, "   ")])

    assert len(chunks) > 1
    assert chunks[0].start_seconds == 0.0
    assert chunks[-1].end_seconds == 160.0
    assert all(c.page_start is None and c.heading is None for c in chunks)
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)
    # Chunks follow each other in time without gaps or overlap.
    for before, after in zip(chunks, chunks[1:]):
        assert before.end_seconds == after.start_seconds
    assert " ".join(c.text for c in chunks) == " ".join(
        " ".join(text.split()) for _, _, text in segments
    )


def test_no_segments_give_no_time_chunks():
    assert build_time_chunks([]) == []


# --- YouTube links -----------------------------------------------------------

def test_video_id_is_found_in_every_link_form():
    video_id = "jNQXAC9IVRw"
    links = [
        f"https://www.youtube.com/watch?v={video_id}",
        f"https://youtube.com/watch?v={video_id}&t=42s&list=PL123",
        f"https://m.youtube.com/watch?feature=share&v={video_id}",
        f"http://www.youtube.com/watch?v={video_id}",
        f"www.youtube.com/watch?v={video_id}",
        f"https://youtu.be/{video_id}",
        f"https://youtu.be/{video_id}?si=abc&t=10",
        f"https://www.youtube.com/shorts/{video_id}",
        f"https://www.youtube.com/embed/{video_id}?start=3",
        f"https://www.youtube.com/live/{video_id}",
        f"  https://youtu.be/{video_id}  ",
    ]
    for link in links:
        assert parse_video_id(link) == video_id, link


def test_other_links_are_rejected():
    links = [
        "",
        "   ",
        "not a link",
        "https://www.youtube.com/",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=jNQXAC9IVRw-too-long",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/@channel",
        "https://vimeo.com/123456789",
        "https://evil.example/watch?v=jNQXAC9IVRw",
        "https://youtube.com.evil.example/watch?v=jNQXAC9IVRw",
        "javascript:alert(1)//youtu.be/jNQXAC9IVRw",
        "ftp://youtu.be/jNQXAC9IVRw",
    ]
    for link in links:
        assert parse_video_id(link) is None, link


def test_every_youtube_request_has_a_time_limit(monkeypatch):
    import requests

    seen = {}

    def fake_request(self, method, url, **kwargs):
        seen.update(kwargs)
        raise requests.ConnectionError("no network in tests")

    monkeypatch.setattr(requests.Session, "request", fake_request)

    try:
        youtube._http_session().get("https://www.youtube.com/")
    except requests.ConnectionError:
        pass

    assert seen["timeout"] == youtube.REQUEST_TIMEOUT_SECONDS


def test_unreachable_youtube_is_reported_as_fetch_failed(monkeypatch):
    import pytest
    import requests

    def fake_request(self, method, url, **kwargs):
        raise requests.ConnectionError("no network in tests")

    monkeypatch.setattr(requests.Session, "request", fake_request)

    with pytest.raises(youtube.YouTubeError) as error:
        youtube.fetch_youtube("jNQXAC9IVRw")

    assert error.value.code == youtube.FETCH_FAILED
# --- findings of the strict review ---------------------------------------------

def test_mathematical_notation_is_not_flattened():
    assert clean_extracted_text("x² و 10⁻³ و H₂O و ½") == "x² و 10⁻³ و H₂O و ½"
    # Presentation forms are still converted.
    assert clean_extracted_text("\ufefb \ufb56") == "لا پ"


def test_unstorable_characters_are_removed():
    assert clean_extracted_text("a\ud800b") == "ab"


def test_healthy_text_with_real_mirror_words_is_ready():
    healthy = (
        "نمونه\u200cای از متن سالم که رد پای دوش و ره در آن هست و این برای "
        "آن است که باید با خود بود. "
    ) * 6
    assert assess_extraction_quality([healthy]) == ("READY", None)


def test_numbered_first_and_last_lines_are_not_mistaken_for_headers():
    pages = [
        (i + 1, f"ماده {7 * i + 3}\nمتن صفحه {i} الف\nپاسخ: گزینه {(i * 3) % 4 + 1}")
        for i in range(5)
    ]
    lines = [line for c in build_chunks(pages) for line in c.text.split("\n")]

    assert sum(line.startswith("ماده") for line in lines) == 5
    assert sum(line.startswith("پاسخ") for line in lines) == 5


def test_numbered_lists_are_not_mistaken_for_chapters():
    body = "\n".join(f"متن شماره {i}" for i in range(12))
    documents = [
        # the case from the review
        "1- فصل اول\nمتن\n3 -2- غلط\n1 -1 - پرداخت\n1- پیش پرداخت انجام می شود.\n"
        f"2- قسط دوم\n12 - 5 = 7\n10- 20 درصد از مبلغ\nمتن پایانی\n{body}\n2- فصل دوم\nمتن",
        # a list of three items inside chapter 1
        f"1- فصل اول\nمتن\n1- مورد یک\n2- مورد دو\n3- مورد سه\n{body}\n2- فصل دوم\nمتن",
        # a list with a single item
        f"1- فصل اول\nمتن\n1- تنها مورد\n{body}\n2- فصل دوم\nمتن",
    ]

    for text in documents:
        headings = {c.heading.split(HEADING_SEPARATOR)[0] for c in build_chunks([(1, text)])}
        assert headings == {"1- فصل اول", "2- فصل دوم"}, text


def test_a_line_longer_than_a_chunk_is_cut():
    chunks = build_chunks([(1, "کلمه " * 2000)])
    assert len(chunks) > 1
    assert max(len(c.text) for c in chunks) <= MAX_CHUNK_CHARS

    timed = build_time_chunks([(0.0, 9.0, "word " * 2000)])
    assert len(timed) > 1
    assert max(len(c.text) for c in timed) <= MAX_CHUNK_CHARS
    assert {(c.start_seconds, c.end_seconds) for c in timed} == {(0.0, 9.0)}


def _run_body_limit(headers, body_parts):
    import asyncio

    from app.core.body_limit import BodySizeLimitMiddleware

    seen = []
    parts = list(body_parts)

    async def inner(scope, receive, send):
        while True:
            message = await receive()
            seen.append(len(message["body"]))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        part = parts.pop(0)
        return {"type": "http.request", "body": part, "more_body": bool(parts)}

    sent = []

    async def send(message):
        sent.append(message)

    middleware = BodySizeLimitMiddleware(inner, limit_for=lambda path: 10)
    asyncio.run(
        middleware({"type": "http", "path": "/", "headers": headers}, receive, send)
    )

    return sent[0]["status"], seen


def test_body_limit_refuses_a_declared_size_without_reading():
    status, seen = _run_body_limit([(b"content-length", b"11")], [b"x" * 11])
    assert (status, seen) == (413, [])


def test_body_limit_stops_reading_an_undeclared_body():
    status, seen = _run_body_limit([], [b"12345", b"12345", b"1", b"12345"])
    # The third part crosses the limit and is never handed on.
    assert (status, seen) == (413, [5, 5])


def test_body_limit_lets_a_small_body_through():
    status, seen = _run_body_limit([(b"content-length", b"10")], [b"12345", b"12345"])
    assert (status, seen) == (200, [5, 5])


def test_youtube_library_errors_are_mapped_to_reasons(monkeypatch):
    import pytest
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api import _errors as errors

    video = "jNQXAC9IVRw"
    cases = [
        (errors.TranscriptsDisabled(video), youtube.NO_TRANSCRIPT),
        (errors.NoTranscriptFound(video, ["en"], []), youtube.NO_TRANSCRIPT),
        (errors.VideoUnavailable(video), youtube.VIDEO_UNAVAILABLE),
        (errors.InvalidVideoId(video), youtube.VIDEO_UNAVAILABLE),
        (errors.AgeRestricted(video), youtube.VIDEO_UNAVAILABLE),
        (errors.RequestBlocked(video), youtube.BLOCKED),
        (errors.IpBlocked(video), youtube.BLOCKED),
        (RuntimeError("anything else"), youtube.FETCH_FAILED),
    ]

    for library_error, expected in cases:
        def fail(self, video_id, _error=library_error):
            raise _error

        monkeypatch.setattr(YouTubeTranscriptApi, "list", fail)

        with pytest.raises(youtube.YouTubeError) as raised:
            youtube.fetch_youtube(video)

        assert raised.value.code == expected, type(library_error).__name__


def test_youtube_captions_become_timed_segments(monkeypatch):
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._transcripts import (
        FetchedTranscript,
        FetchedTranscriptSnippet,
    )

    fetched = FetchedTranscript(
        snippets=[
            FetchedTranscriptSnippet(text="hello", start=0.0, duration=1.5),
            FetchedTranscriptSnippet(text="world", start=1.5, duration=2.0),
        ],
        video_id="jNQXAC9IVRw",
        language="English",
        language_code="en",
        is_generated=False,
    )

    class OneTranscript:
        def fetch(self):
            return fetched

    monkeypatch.setattr(
        YouTubeTranscriptApi, "list", lambda self, video_id: [OneTranscript()]
    )
    monkeypatch.setattr(youtube, "_fetch_title", lambda video_id: "A title")

    result = youtube.fetch_youtube("jNQXAC9IVRw")

    assert result.title == "A title"
    assert result.language == "en"
    assert result.segments == [(0.0, 1.5, "hello"), (1.5, 3.5, "world")]

    monkeypatch.setattr(YouTubeTranscriptApi, "list", lambda self, video_id: [])
    try:
        youtube.fetch_youtube("jNQXAC9IVRw")
        raise AssertionError("expected NO_TRANSCRIPT")
    except youtube.YouTubeError as error:
        assert error.code == youtube.NO_TRANSCRIPT
def test_each_path_has_its_own_size_limit():
    from app.core.limits import (
        MAX_AUDIO_SIZE_BYTES,
        MAX_ORDINARY_REQUEST_BYTES,
        MAX_PDF_SIZE_BYTES,
        request_limit_for,
    )

    assert MAX_PDF_SIZE_BYTES < request_limit_for("/projects/3/sources/pdf") < MAX_PDF_SIZE_BYTES * 1.1
    assert MAX_AUDIO_SIZE_BYTES < request_limit_for("/projects/3/sources/audio/") < MAX_AUDIO_SIZE_BYTES * 1.1
    for path in ("/projects/", "/auth/register", "/sources/3/chunks/", "/pdf", ""):
        assert request_limit_for(path) == MAX_ORDINARY_REQUEST_BYTES, path


def test_slow_jobs_are_done_one_at_a_time_and_in_order(monkeypatch):
    import threading
    import time

    from app.core import worker

    monkeypatch.setattr(worker, "_INLINE", False)

    running = []
    overlaps = []
    done = []
    finished = threading.Event()

    def job(number):
        running.append(number)
        if len(running) > 1:
            overlaps.append(list(running))
        time.sleep(0.02)
        running.remove(number)
        done.append(number)
        if number == "broken":
            raise RuntimeError("a job that fails")
        if number == 5:
            finished.set()

    for number in (1, 2, "broken", 4, 5):
        worker.submit(job, number)

    assert finished.wait(timeout=5)
    # In order, never two at once, and a failing job does not stop the line.
    assert done == [1, 2, "broken", 4, 5]
    assert overlaps == []


def test_a_full_waiting_line_refuses_new_jobs(monkeypatch):
    import threading

    import pytest

    from app.core import worker

    monkeypatch.setattr(worker, "_INLINE", False)
    monkeypatch.setattr(worker, "MAX_WAITING_JOBS", 2)

    release = threading.Event()
    started = threading.Event()

    def blocked():
        started.set()
        release.wait(timeout=5)

    worker.submit(blocked)
    assert started.wait(timeout=5)
    worker.submit(lambda: None)
    worker.submit(lambda: None)

    assert not worker.has_room()
    with pytest.raises(worker.WorkerBusy):
        worker.submit(lambda: None)

    release.set()
    worker._jobs.join()
    assert worker.has_room()


def test_youtube_requests_go_through_the_proxy_when_one_is_set(monkeypatch):
    monkeypatch.delenv("YOUTUBE_PROXY_URL", raising=False)
    assert youtube._http_session().proxies == {}

    monkeypatch.setenv("YOUTUBE_PROXY_URL", " http://user:pass@proxy.example:8080 ")
    assert youtube._http_session().proxies == {
        "http": "http://user:pass@proxy.example:8080",
        "https": "http://user:pass@proxy.example:8080",
    }
