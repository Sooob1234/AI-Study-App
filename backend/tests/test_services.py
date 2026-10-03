"""Checks for the source-processing services. They need no database.

Run from the backend folder:  python -m pytest
"""

from app.services.chunking import HEADING_SEPARATOR, build_chunks
from app.services.quality_check import assess_extraction_quality
from app.services.text_cleaning import clean_extracted_text


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
    assert assess_extraction_quality([GOOD, GOOD]) == "READY"


def test_reversed_text_needs_review():
    assert assess_extraction_quality([REVERSED, REVERSED]) == "NEEDS_REVIEW"


def test_empty_pages_need_review():
    assert assess_extraction_quality(["", ""]) == "NEEDS_REVIEW"
    assert assess_extraction_quality([]) == "NEEDS_REVIEW"


def test_english_text_is_ready():
    assert assess_extraction_quality(["A page of plain English text."]) == "READY"


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
