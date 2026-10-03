"""Split a source's page texts into chunks, section by section.

A chunk is a small piece of the source text that keeps where it came from:
its page numbers and the heading it sits under. Later steps (search,
summaries, quizzes) read chunks instead of whole sources, and use the page
numbers to cite "page 12". This module belongs to the source-processing
layer and contains no AI logic.
"""

import re
from dataclasses import dataclass

# CHUNKING_V1

# A chunk is closed once it reaches this many characters.
MAX_CHUNK_CHARS = 1500
# A final piece shorter than this is joined to the chunk before it.
MIN_CHUNK_CHARS = 300
# Headings down to this depth always start a new chunk ("3" and "3-2").
BOUNDARY_LEVEL = 2
# A line repeated at the top or bottom of this share of pages is a
# running header or footer and is removed.
REPEATED_LINE_SHARE = 0.6

# A numbered heading such as "3- title", "3 -2- title" or "10 -1 -4 - title".
_HEADING = re.compile(
    r"^\s*(\d{1,2}(?:\s*-\s*\d{1,2}){0,3})\s*-\s*(\S.*)$"
)
_DIGITS = re.compile(r"[0-9۰-۹٠-٩]+")
HEADING_SEPARATOR = " › "
MAX_HEADING_CHARS = 120


@dataclass
class Chunk:
    chunk_index: int
    page_start: int
    page_end: int
    heading: str | None
    text: str


def _parse_heading(line: str) -> tuple[int, str] | None:
    """Return (level, title) if the line is a numbered heading."""
    if len(line) > MAX_HEADING_CHARS:
        return None

    match = _HEADING.match(line)
    if match is None:
        return None

    level = len(re.findall(r"\d+", match.group(1)))
    return level, line.strip()


def _repeated_line(lines: list[str], page_count: int) -> str | None:
    """The digit-free form of a line that repeats on most pages, if any."""
    if page_count < 3:
        return None

    counts: dict[str, int] = {}
    for line in lines:
        key = _DIGITS.sub("", line).strip()
        if key:
            counts[key] = counts.get(key, 0) + 1

    if not counts:
        return None

    key, count = max(counts.items(), key=lambda item: item[1])
    if count / page_count >= REPEATED_LINE_SHARE:
        return key

    return None


def _page_lines(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """All non-empty lines with their page number, without headers/footers."""
    split_pages = [
        (number, [line for line in text.split("\n") if line.strip()])
        for number, text in pages
    ]
    filled = [lines for _, lines in split_pages if lines]

    header = _repeated_line([lines[0] for lines in filled], len(pages))
    footer = _repeated_line([lines[-1] for lines in filled], len(pages))

    result: list[tuple[int, str]] = []
    for number, lines in split_pages:
        # A page whose only line looks like the header is kept as it is.
        if len(lines) > 1 and header and _DIGITS.sub("", lines[0]).strip() == header:
            lines = lines[1:]
        if len(lines) > 1 and footer and _DIGITS.sub("", lines[-1]).strip() == footer:
            lines = lines[:-1]
        result.extend((number, line) for line in lines)

    return result


def build_chunks(pages: list[tuple[int, str]]) -> list[Chunk]:
    """Turn (page_number, text) pairs into an ordered list of chunks."""
    chunks: list[Chunk] = []
    path: list[str] = []          # titles of the current level 1..2 headings
    current: list[tuple[int, str]] = []
    current_heading: str | None = None
    # Level of the heading if the running chunk holds nothing but headings.
    bare_level: int | None = None

    def close(joinable: bool) -> None:
        nonlocal current
        if not current:
            return

        text = "\n".join(line for _, line in current)
        page_start = current[0][0]
        page_end = current[-1][0]
        current = []

        previous = chunks[-1] if chunks else None
        if (
            joinable
            and previous is not None
            and previous.heading == current_heading
            and len(text) < MIN_CHUNK_CHARS
        ):
            previous.text = previous.text + "\n" + text
            previous.page_end = page_end
            return

        chunks.append(Chunk(
            chunk_index=len(chunks),
            page_start=page_start,
            page_end=page_end,
            heading=current_heading,
            text=text,
        ))

    for page_number, line in _page_lines(pages):
        heading = _parse_heading(line)
        size = sum(len(text) + 1 for _, text in current)

        if heading is not None and heading[0] <= BOUNDARY_LEVEL:
            level, title = heading
            # A new section: finish the running chunk and update the path.
            # A heading directly followed by its own sub-heading stays with
            # it, so no chunk consists of a heading line alone.
            if not (bare_level is not None and level > bare_level):
                close(joinable=True)
            path = path[:level - 1] + [title]
            current_heading = HEADING_SEPARATOR.join(path)
        elif current and (
            size + len(line) > MAX_CHUNK_CHARS
            # Prefer to cut just before a deeper heading when nearly full.
            or (heading is not None and size > MAX_CHUNK_CHARS * 0.6)
        ):
            close(joinable=False)

        if heading is not None and heading[0] <= BOUNDARY_LEVEL:
            bare_level = heading[0]
        else:
            bare_level = None

        current.append((page_number, line))

    close(joinable=True)
    return chunks
