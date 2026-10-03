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
