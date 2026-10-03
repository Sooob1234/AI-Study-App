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

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_SURROGATES = re.compile(r"[\ud800-\udfff]")
_PRESENTATION_FORMS = re.compile(r"[\uFB50-\uFDFF\uFE70-\uFEFC]+")

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
            # Swap everywhere except inside list markers such as "1)",
            # which must stay as they are.
            table = {ord(opener): closer, ord(closer): opener}
            parts = []
            position = 0
            for marker in _LIST_MARKER.finditer(text):
                parts.append(text[position:marker.start()].translate(table))
                parts.append(marker.group())
                position = marker.end()
            parts.append(text[position:].translate(table))
            text = "".join(parts)

    return text


def clean_extracted_text(text: str | None) -> str:
    """Return extracted text as standard, searchable text."""
    if not text:
        return ""

    # Characters that cannot be stored at all.
    text = _SURROGATES.sub("", text)

    # Presentation-form letters -> standard letters. Only the Arabic-script
    # presentation forms are converted; everything else is left as it is,
    # so that x² does not turn into x2.
    text = _PRESENTATION_FORMS.sub(
        lambda match: unicodedata.normalize("NFKC", match.group()),
        text,
    )

    # Invisible control characters (the database rejects some of them);
    # line breaks and tabs are kept.
    text = _CONTROL_CHARS.sub("", text)

    for old, new in _CHAR_REPLACEMENTS.items():
        text = text.replace(old, new)

    text = _fix_mirrored_brackets(text)

    # Tidy spacing: single spaces, no spaces around line breaks,
    # at most one empty line in a row
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
