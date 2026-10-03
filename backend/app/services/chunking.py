"""Split a source's page texts into chunks, section by section.

A chunk is a small piece of the source text that keeps where it came from:
its page numbers and the heading it sits under. Later steps (search,
summaries, quizzes) read chunks instead of whole sources, and use the page
numbers to cite "page 12". This module belongs to the source-processing
layer and contains no AI logic.
"""

import re
from dataclasses import dataclass

# CHUNKING_V2

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
# A heading is a title, not a sentence: it does not end like one.
_SENTENCE_END = (".", ":", "،", "؛", ",", ";")
HEADING_SEPARATOR = " › "
MAX_HEADING_CHARS = 120


@dataclass
class Chunk:
    chunk_index: int
    heading: str | None
    text: str
    # A chunk comes either from pages (PDF) or from a time span (video, audio).
    page_start: int | None = None
    page_end: int | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None


def _parse_heading(line: str) -> tuple[list[int], str] | None:
    """Return (numbers, title) if the line has the shape of a heading."""
    if len(line) > MAX_HEADING_CHARS:
        return None

    match = _HEADING.match(line)
    if match is None:
        return None

    numbers = [int(number) for number in re.findall(r"\d+", match.group(1))]
    return numbers, line.strip()


class _HeadingTracker:
    """Decides which heading-shaped lines really are headings.

    A numbered list ("1- ...", "2- ...") has the same shape as a chapter
    heading, so shape alone is not enough. A line is accepted only if it
    continues the numbering of the document:
    - a chapter must carry the number after the previous chapter and must
      not end like a sentence;
    - a line that continues a numbered list a few lines above it is a list
      item, even if its number happens to be the next chapter number;
    - a section such as "3 -2-" must sit under chapter 3.
    """

    # List items follow each other closely; a chapter comes after more text.
    LIST_GAP_LINES = 8

    def __init__(self) -> None:
        self.chapter: int | None = None
        self._list_next: int | None = None
        self._list_line = 0

    def _is_next_chapter(self, number: int) -> bool:
        if self.chapter is None:
            return True

        expected = self.chapter + 1
        # Text extraction sometimes reverses the digits ("21" for "12").
        return number == expected or int(str(number)[::-1]) == expected

    def _note_list_item(self, number: int, line_index: int) -> None:
        self._list_next = number + 1
        self._list_line = line_index

    def accept(
        self, numbers: list[int], title: str, line_index: int
    ) -> int | None:
        """Return the heading level if the line is a real heading."""
        if len(numbers) > 1:
            if self.chapter is None or numbers[0] != self.chapter:
                return None
            return len(numbers)

        number = numbers[0]

        continues_list = (
            self._list_next == number
            and line_index - self._list_line <= self.LIST_GAP_LINES
        )
        ends_like_sentence = title.rstrip().endswith(_SENTENCE_END)
        restarts_numbering = self.chapter is not None and number <= self.chapter

        if continues_list or ends_like_sentence or restarts_numbering:
            self._note_list_item(number, line_index)
            return None

        if not self._is_next_chapter(number):
            return None

        self.chapter = number if self.chapter is None else self.chapter + 1
        self._list_next = None
        return 1


def _repeated_line(
    lines: list[tuple[int, str]], page_count: int
) -> str | None:
    """The digit-free form of a running header or footer, if there is one.

    `lines` holds (page_number, line) for the first (or last) line of each
    page. A running header is the same on most pages apart from the page
    number. A line whose number does not follow the page number (such as
    "Question 7" at the top of page 2) is content, not a header.
    """
    if page_count < 3:
        return None

    groups: dict[str, list[tuple[int, str]]] = {}
    for page_number, line in lines:
        key = _DIGITS.sub("", line).strip()
        if key:
            groups.setdefault(key, []).append((page_number, line))

    if not groups:
        return None

    key, members = max(groups.items(), key=lambda item: len(item[1]))
    if len(members) / page_count < REPEATED_LINE_SHARE:
        return None

    offsets = set()
    for page_number, line in members:
        numbers = _DIGITS.findall(line)
        if len(numbers) > 1:
            return None
        if numbers:
            offsets.add(int(numbers[0]) - page_number)

    # Either no number at all, or always the page number (plus a fixed shift).
    if len(offsets) > 1:
        return None

    return key


def _split_long_line(line: str) -> list[str]:
    """Cut a line longer than a chunk into pieces, at spaces where possible."""
    pieces = []

    while len(line) > MAX_CHUNK_CHARS:
        cut = line.rfind(" ", 0, MAX_CHUNK_CHARS + 1)
        if cut <= 0:
            cut = MAX_CHUNK_CHARS
        pieces.append(line[:cut].rstrip())
        line = line[cut:].lstrip()

    if line:
        pieces.append(line)

    return pieces


def _page_lines(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """All non-empty lines with their page number, without headers/footers."""
    split_pages = [
        (number, [line for line in text.split("\n") if line.strip()])
        for number, text in pages
    ]
    filled = [(number, lines) for number, lines in split_pages if lines]

    header = _repeated_line(
        [(number, lines[0]) for number, lines in filled], len(pages)
    )
    footer = _repeated_line(
        [(number, lines[-1]) for number, lines in filled], len(pages)
    )

    result: list[tuple[int, str]] = []
    for number, lines in split_pages:
        # A page whose only line looks like the header is kept as it is.
        if len(lines) > 1 and header and _DIGITS.sub("", lines[0]).strip() == header:
            lines = lines[1:]
        if len(lines) > 1 and footer and _DIGITS.sub("", lines[-1]).strip() == footer:
            lines = lines[:-1]

        for line in lines:
            result.extend((number, piece) for piece in _split_long_line(line))

    return result


def build_chunks(pages: list[tuple[int, str]]) -> list[Chunk]:
    """Turn (page_number, text) pairs into an ordered list of chunks."""
    chunks: list[Chunk] = []
    tracker = _HeadingTracker()
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

    for line_index, (page_number, line) in enumerate(_page_lines(pages)):
        level = None
        parsed = _parse_heading(line)
        if parsed is not None:
            level = tracker.accept(*parsed, line_index)

        size = sum(len(text) + 1 for _, text in current)

        if level is not None and level <= BOUNDARY_LEVEL:
            # A new section: finish the running chunk and update the path.
            # A heading directly followed by its own sub-heading stays with
            # it, so no chunk consists of a heading line alone.
            if not (bare_level is not None and level > bare_level):
                close(joinable=True)
            path = path[:level - 1] + [line.strip()]
            current_heading = HEADING_SEPARATOR.join(path)
        elif current and (
            size + len(line) > MAX_CHUNK_CHARS
            # Prefer to cut just before a deeper heading when nearly full.
            or (level is not None and size > MAX_CHUNK_CHARS * 0.6)
        ):
            close(joinable=False)

        if level is not None and level <= BOUNDARY_LEVEL:
            bare_level = level
        else:
            bare_level = None

        current.append((page_number, line))

    close(joinable=True)
    return chunks


def build_time_chunks(segments: list[tuple[float, float, str]]) -> list[Chunk]:
    """Turn (start_seconds, end_seconds, text) transcript pieces into chunks.

    Transcript pieces are short fragments of speech, so they are joined
    with spaces until a chunk is full. Each chunk keeps the time span it
    covers, so that answers can cite "00:24:18".
    """
    chunks: list[Chunk] = []
    current: list[tuple[float, float, str]] = []
    size = 0

    def close() -> None:
        nonlocal current, size
        if not current:
            return

        chunks.append(Chunk(
            chunk_index=len(chunks),
            heading=None,
            text=" ".join(text for _, _, text in current),
            start_seconds=current[0][0],
            end_seconds=max(end for _, end, _ in current),
        ))
        current = []
        size = 0

    for start, end, text in segments:
        text = " ".join(text.split())

        # A single piece longer than a chunk is cut; its parts share its time.
        for piece in _split_long_line(text):
            if current and size + len(piece) > MAX_CHUNK_CHARS:
                close()

            current.append((start, end, piece))
            size += len(piece) + 1

    close()
    return chunks
