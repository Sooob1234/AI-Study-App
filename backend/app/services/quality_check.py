"""Quality check of text extracted from a source.

Some PDFs give no text at all (scanned pages), and some give Persian text
with the letters of each word in reverse order. In both cases the text is
not usable, so the source must not be marked READY. This module decides
that. It belongs to the source-processing layer and contains no AI logic.
"""

import re

# QUALITY_CHECK_V1

# Very common Persian words whose mirror image is not a word. In healthy
# text they appear often; in broken text their mirror images ("زا" for "از")
# appear instead. Words such as "در" are left out on purpose, because their
# mirror image ("رد") is a real word.
_COMMON_WORDS = frozenset({
    "از", "به", "که", "را", "با", "این", "است", "برای", "آن",
    "باید", "کند", "شده", "بود", "خود", "دارد",
})

# A word may contain the half-space (zero-width non-joiner), as in "می‌شود".
_PERSIAN_WORD = re.compile(r"[\u0600-\u06FF\u200c]+")
_LETTER = re.compile(r"[^\W\d_]")

# A page with fewer letters than this counts as having no text.
MIN_LETTERS_PER_PAGE = 20
# If at least this share of pages has no text, the source needs review.
MAX_EMPTY_PAGE_SHARE = 0.5
# The reversed-text test is only trusted with this many common words.
MIN_COMMON_WORDS = 20
# Above this share of reversed common words, the text is considered broken.
MAX_REVERSED_SHARE = 0.10


def empty_page_share(page_texts: list[str]) -> float:
    """Share of pages (0 to 1) that contain practically no text."""
    if not page_texts:
        return 1.0

    empty = sum(
        1 for text in page_texts
        if len(_LETTER.findall(text)) < MIN_LETTERS_PER_PAGE
    )
    return empty / len(page_texts)


def reversed_word_share(page_texts: list[str]) -> float:
    """Share (0 to 1) of common Persian words that came out reversed."""
    normal = 0
    reversed_count = 0

    for text in page_texts:
        for word in _PERSIAN_WORD.findall(text):
            if word in _COMMON_WORDS:
                normal += 1
            elif word[::-1] in _COMMON_WORDS:
                reversed_count += 1

    total = normal + reversed_count
    if total < MIN_COMMON_WORDS:
        return 0.0

    return reversed_count / total


# Reasons reported together with NEEDS_REVIEW.
NO_TEXT = "NO_TEXT"
REVERSED_TEXT = "REVERSED_TEXT"


def assess_extraction_quality(page_texts: list[str]) -> tuple[str, str | None]:
    """Return (status, reason) for a source from its extracted texts.

    The status is "READY" (reason None) or "NEEDS_REVIEW" with a reason.
    """
    if empty_page_share(page_texts) >= MAX_EMPTY_PAGE_SHARE:
        return "NEEDS_REVIEW", NO_TEXT

    if reversed_word_share(page_texts) > MAX_REVERSED_SHARE:
        return "NEEDS_REVIEW", REVERSED_TEXT

    return "READY", None
