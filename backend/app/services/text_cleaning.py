"""Clean-up of text extracted from sources (PDF pages, later transcripts).

PDF libraries often return Persian text in a form that looks right on screen
but is stored with non-standard characters, which breaks search. This module
turns it into standard Persian text. It belongs to the source-processing
layer and contains no AI logic.
"""

import re
import unicodedata

# Arabic letter variants -> standard Persian letters
_CHAR_REPLACEMENTS = {
    "\u064A": "\u06CC",  # Arabic yeh -> Persian yeh
    "\u0649": "\u06CC",  # alef maksura -> Persian yeh
    "\u0643": "\u06A9",  # Arabic kaf -> Persian kaf
    "\u0640": "",        # kashida (stretching character)
    "\u00A0": " ",       # non-breaking space
    "\u200F": "",        # right-to-left mark
    "\u200E": "",        # left-to-right mark
    "\uFEFF": "",        # byte order mark
}

_BRACKET_PAIRS = [("(", ")"), ("\u00AB", "\u00BB"), ("[", "]")]

# A number at the start of a line followed by a single bracket, e.g. "1)"
_LIST_MARKER = re.compile(r"^\s*\d+\s*[()]", re.MULTILINE)


def _unbalanced_count(text: str, opener: str, closer: str) -> int:
    """How many closing brackets appear before any matching opening bracket."""
    depth = 0
    errors = 0
    for char in text:
        if char == opener:
            depth += 1
        elif char == closer:
            if depth == 0:
                errors += 1
            else:
                depth -= 1
    return errors + depth


def _fix_mirrored_brackets(text: str) -> str:
    """Swap bracket pairs that came out reversed, e.g. ')word(' -> '(word)'."""
    for opener, closer in _BRACKET_PAIRS:
        if opener not in text and closer not in text:
            continue

        # Numbered-list markers such as "1)" have no partner bracket and
        # would distort the count, so they are left out of the decision.
        sample = _LIST_MARKER.sub("", text)

        as_is = _unbalanced_count(sample, opener, closer)
        swapped = _unbalanced_count(sample, closer, opener)

        if swapped < as_is:
            text = text.translate({ord(opener): closer, ord(closer): opener})

    return text


def clean_extracted_text(text: str | None) -> str:
    """Return extracted text as standard, searchable text."""
    if not text:
        return ""

    # Presentation-form letters -> standard letters
    text = unicodedata.normalize("NFKC", text)

    for old, new in _CHAR_REPLACEMENTS.items():
        text = text.replace(old, new)

    text = _fix_mirrored_brackets(text)

    # Tidy spacing: single spaces, no spaces around line breaks,
    # at most one empty line in a row
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
