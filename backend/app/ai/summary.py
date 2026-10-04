"""Building a summary of a source from its chunks.

This is AI output generation. It reads the chunks that source processing
produced and never touches files, pages or transcripts itself.

How it works, in order:
1. The chunks are grouped into sections (by chapter heading) and each
   section is cut into parts small enough for the model to read whole.
2. The model summarises every part on its own (key points, tables,
   warnings). Every part is read, so nothing is skipped by design.
3. The outline (tree of headings) and the coverage table are built by the
   program itself, not by the model, so they cannot be invented.
4. One last question to the model writes the short overview.
"""

import os
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.ai import llm
from app.services.chunking import HEADING_SEPARATOR

# SUMMARY_V1

SOURCE_ONLY = "SOURCE_ONLY"
SOURCE_PLUS_AI = "SOURCE_PLUS_AI"

MAX_POINTS_PER_PART = 12
MAX_TABLES_PER_PART = 4
MAX_TABLE_ROWS = 40
MAX_TABLE_COLUMNS = 6


def max_part_chars() -> int:
    """How much text is given to the model at once.

    Small enough for a local open model to read in full; a model with a
    large context can be given more through AI_MAX_INPUT_CHARS.
    """
    return int(os.getenv("AI_MAX_INPUT_CHARS") or 3000)


# ---------------------------------------------------------------- input

@dataclass
class ChunkIn:
    heading: str | None
    text: str
    page_start: int | None = None
    page_end: int | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None

    def ref(self) -> dict:
        if self.page_start is not None:
            return {"page_start": self.page_start, "page_end": self.page_end}
        return {
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
        }


@dataclass
class Part:
    chunks: list[ChunkIn]


@dataclass
class Section:
    title: str | None                 # None when the source has no headings
    parts: list[Part] = field(default_factory=list)


def _merge_refs(chunks: list[ChunkIn]) -> dict:
    first, last = chunks[0], chunks[-1]
    if first.page_start is not None:
        return {"page_start": first.page_start, "page_end": last.page_end}
    return {
        "start_seconds": first.start_seconds,
        "end_seconds": last.end_seconds,
    }


def _top_heading(chunk: ChunkIn) -> str | None:
    if not chunk.heading:
        return None
    return chunk.heading.split(HEADING_SEPARATOR)[0]


def _sub_heading(chunk: ChunkIn) -> str | None:
    if not chunk.heading or HEADING_SEPARATOR not in chunk.heading:
        return None
    return chunk.heading.split(HEADING_SEPARATOR)[1]


# A piece of text shorter than this, before the first heading, is a title
# line rather than content of its own.
SHORT_OPENER_CHARS = 100


def _attach_short_openers(chunks: list[ChunkIn]) -> list[ChunkIn]:
    """Join a short untitled opening (such as the document's title line)
    to the chunk after it, instead of asking the model about it alone."""
    result: list[ChunkIn] = []
    opener: ChunkIn | None = None

    for chunk in chunks:
        if opener is not None:
            chunk = ChunkIn(
                heading=chunk.heading,
                text=opener.text + "\n" + chunk.text,
                page_start=opener.page_start if opener.page_start is not None else chunk.page_start,
                page_end=chunk.page_end,
                start_seconds=opener.start_seconds if opener.start_seconds is not None else chunk.start_seconds,
                end_seconds=chunk.end_seconds,
            )
            opener = None

        if (
            chunk.heading is None
            and len(chunk.text.strip()) < SHORT_OPENER_CHARS
            and not result
        ):
            opener = chunk
            continue

        result.append(chunk)

    if opener is not None:
        result.append(opener)

    return result


def plan_sections(chunks: list[ChunkIn]) -> list[Section]:
    """Group chunks into sections and cut each section into parts."""
    limit = max_part_chars()
    sections: list[Section] = []
    chunks = _attach_short_openers(chunks)

    for chunk in chunks:
        title = _top_heading(chunk)

        if not sections or sections[-1].title != title:
            sections.append(Section(title=title))
        section = sections[-1]

        part = section.parts[-1] if section.parts else None
        size = sum(len(c.text) for c in part.chunks) if part else 0

        if part is None or size + len(chunk.text) > limit:
            section.parts.append(Part(chunks=[chunk]))
        else:
            part.chunks.append(chunk)

    # A source without headings has one untitled section; each of its
    # parts becomes a section of its own, titled by the model.
    result: list[Section] = []
    for section in sections:
        if section.title is None:
            result.extend(Section(title=None, parts=[p]) for p in section.parts)
        else:
            result.append(section)

    return result


def build_outline(chunks: list[ChunkIn]) -> list[dict]:
    """The tree of headings, taken from the chunks themselves."""
    outline: list[dict] = []

    for chunk in chunks:
        top = _top_heading(chunk)
        if top is None:
            continue

        if not outline or outline[-1]["title"] != top:
            outline.append({"title": top, "ref": chunk.ref(), "children": []})
        node = outline[-1]
        node["ref"] = _merge_refs_dict(node["ref"], chunk.ref())

        sub = _sub_heading(chunk)
        if sub is None:
            continue
        if not node["children"] or node["children"][-1]["title"] != sub:
            node["children"].append({"title": sub, "ref": chunk.ref()})
        child = node["children"][-1]
        child["ref"] = _merge_refs_dict(child["ref"], chunk.ref())

    return outline


def _merge_refs_dict(first: dict, last: dict) -> dict:
    if "page_start" in first:
        return {"page_start": first["page_start"], "page_end": last["page_end"]}
    return {
        "start_seconds": first["start_seconds"],
        "end_seconds": last["end_seconds"],
    }


# ------------------------------------------------- the model's answer

def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


class _Point(BaseModel):
    text: str
    part: int = 1

    @field_validator("text", mode="before")
    @classmethod
    def clean(cls, value):
        return _text(value)

    @field_validator("part", mode="before")
    @classmethod
    def number(cls, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 1


class _Table(BaseModel):
    title: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    part: int = 1

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value):
        return _text(value)

    @field_validator("columns", mode="before")
    @classmethod
    def clean_columns(cls, value):
        if not isinstance(value, list):
            return []
        return [_text(item) for item in value][:MAX_TABLE_COLUMNS]

    @field_validator("rows", mode="before")
    @classmethod
    def clean_rows(cls, value):
        if not isinstance(value, list):
            return []
        rows = []
        for row in value[:MAX_TABLE_ROWS]:
            if isinstance(row, list):
                rows.append([_text(cell) for cell in row][:MAX_TABLE_COLUMNS])
        return rows

    @field_validator("part", mode="before")
    @classmethod
    def number(cls, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 1


class _PartAnswer(BaseModel):
    title: str = ""
    key_points: list[_Point] = Field(default_factory=list)
    tables: list[_Table] = Field(default_factory=list)
    warnings: list[_Point] = Field(default_factory=list)
    ai_notes: list[str] = Field(default_factory=list)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value):
        return _text(value)[:120]

    @field_validator("key_points", "warnings", "tables", mode="before")
    @classmethod
    def as_list(cls, value):
        if not isinstance(value, list):
            return []
        # A model sometimes gives plain sentences instead of objects.
        return [
            {"text": item} if isinstance(item, str) else item
            for item in value
            if isinstance(item, (str, dict))
        ]

    @field_validator("ai_notes", mode="before")
    @classmethod
    def as_texts(cls, value):
        if not isinstance(value, list):
            return []
        return [_text(item) for item in value if isinstance(item, (str, int, float))]


_PART_SYSTEM = """تو دستیار خلاصه‌نویسی برای دانشجو هستی. متنِ یک بخش از یک منبع درسی به تو داده می‌شود که به چند «تکه» با نشانهٔ [تکه N] تقسیم شده است.

قواعد:
- فقط از همین متن استفاده کن. هیچ چیزی از دانسته‌های خودت اضافه نکن.
- هیچ نکتهٔ مهمی را جا نینداز: تعریف‌ها، قاعده‌ها، استثناها، مثال‌های کلیدی.
- هر نکته یک جملهٔ کوتاه، روشن و کامل به زبان خودِ متن باشد.
- هر جا متن چند چیز را با هم مقایسه می‌کند یا فهرستی از «نادرست و درست» یا «نوع و ویژگی» دارد، آن را به شکل جدول بیاور.
- هشدارها، استثناها و چیزهایی که متن رویشان تأکید کرده را در warnings بیاور.
- برای هر مورد، شمارهٔ تکه‌ای که از آن آمده را در part بنویس.
- اگر متن بد استخراج شده و چیزی نامفهوم است، آن را حدس نزن و کنار بگذار.

پاسخ را فقط به شکل یک شیء JSON بده، بدون هیچ توضیح دیگر، با این ساختار:
{"title": "عنوانی کوتاه برای این بخش", "key_points": [{"text": "...", "part": 1}], "tables": [{"title": "...", "columns": ["...", "..."], "rows": [["...", "..."]], "part": 1}], "warnings": [{"text": "...", "part": 1}]%s}"""

_AI_NOTES_RULE = """

علاوه بر این، اگر توضیحی کوتاه از دانش خودت به فهم این بخش کمک می‌کند، آن را فقط در ai_notes بنویس (حداکثر سه مورد). ai_notes تنها جایی است که اجازه داری چیزی بیرون از متن بگویی."""

_OVERVIEW_SYSTEM = """تو دستیار خلاصه‌نویسی برای دانشجو هستی. فهرست بخش‌های یک منبع درسی و نکته‌های اصلی هر بخش به تو داده می‌شود. در سه تا پنج جمله بنویس که کل این منبع دربارهٔ چیست و چه چیزهایی را پوشش می‌دهد. فقط از همین فهرست استفاده کن.

پاسخ را فقط به شکل یک شیء JSON بده: {"overview": "..."}"""


def _part_prompt(section_title: str | None, part: Part) -> str:
    lines = []
    if section_title:
        lines.append(f"عنوان بخش: {section_title}")
    for index, chunk in enumerate(part.chunks, start=1):
        lines.append(f"\n[تکه {index}]")
        lines.append(chunk.text)
    return "\n".join(lines)


def _ref_for(part: Part, number: int) -> dict:
    """Where an item comes from; a wrong number falls back to the whole part."""
    if 1 <= number <= len(part.chunks):
        return part.chunks[number - 1].ref()
    return _merge_refs(part.chunks)


def _sub_for(part: Part, number: int) -> str | None:
    if 1 <= number <= len(part.chunks):
        return _sub_heading(part.chunks[number - 1])
    return None


def summarise_part(section_title: str | None, part: Part, mode: str) -> dict:
    """Ask the model about one part and return checked, referenced items."""
    system = _PART_SYSTEM % (
        ', "ai_notes": ["..."]' if mode == SOURCE_PLUS_AI else ""
    )
    if mode == SOURCE_PLUS_AI:
        system += _AI_NOTES_RULE

    raw = llm.chat_json(system, _part_prompt(section_title, part))

    try:
        answer = _PartAnswer.model_validate(raw)
    except ValidationError:
        raise llm.LLMError(llm.AI_BAD_ANSWER)

    points = [
        {
            "text": point.text,
            "ref": _ref_for(part, point.part),
            "subheading": _sub_for(part, point.part),
        }
        for point in answer.key_points[:MAX_POINTS_PER_PART]
        if point.text
    ]
    warnings = [
        {"text": point.text, "ref": _ref_for(part, point.part)}
        for point in answer.warnings[:MAX_POINTS_PER_PART]
        if point.text
    ]

    tables = []
    for table in answer.tables[:MAX_TABLES_PER_PART]:
        width = len(table.columns)
        rows = [row for row in table.rows if any(row)]
        if width < 2 or not rows:
            continue
        # Every row gets exactly as many cells as there are columns.
        rows = [(row + [""] * width)[:width] for row in rows]
        tables.append({
            "title": table.title,
            "columns": table.columns,
            "rows": rows,
            "ref": _ref_for(part, table.part),
        })

    if not points and not tables and not warnings:
        # An answer that says nothing about a part that has text.
        raise llm.LLMError(llm.AI_BAD_ANSWER)

    return {
        "title": answer.title,
        "key_points": points,
        "tables": tables,
        "warnings": warnings,
        "ai_notes": (
            [note for note in answer.ai_notes if note][:3]
            if mode == SOURCE_PLUS_AI else []
        ),
    }


def write_overview(sections: list[dict]) -> str:
    """Ask the model for a few sentences about the whole source."""
    lines = []
    for section in sections:
        lines.append(f"- {section['title']}")
        for point in section["key_points"][:3]:
            lines.append(f"    • {point['text']}")
    prompt = "\n".join(lines)[: max_part_chars() + 1500]

    raw = llm.chat_json(_OVERVIEW_SYSTEM, prompt)
    return _text(raw.get("overview"))[:2000]


# ------------------------------------------------------------ the run

@dataclass
class SummaryResult:
    content: dict
    status: str                # READY, NEEDS_REVIEW or FAILED
    status_detail: str | None


INCOMPLETE = "INCOMPLETE"
NOTHING_TO_SUMMARISE = "NOTHING_TO_SUMMARISE"
CANCELLED = "CANCELLED"

ATTEMPTS_PER_PART = 2


def build_summary(
    chunks: list[ChunkIn],
    mode: str,
    on_progress: Callable[[int, int], bool] | None = None,
) -> SummaryResult:
    """Summarise a source.

    `on_progress(done, total)` is called after every part; if it returns
    False the run stops (the output was deleted meanwhile).
    """
    chunks = [chunk for chunk in chunks if chunk.text.strip()]
    if not chunks:
        return SummaryResult({}, "FAILED", NOTHING_TO_SUMMARISE)

    plan = plan_sections(chunks)
    total = sum(len(section.parts) for section in plan)
    done = 0
    last_error: str | None = None

    sections: list[dict] = []
    coverage: list[dict] = []

    for number, section in enumerate(plan, start=1):
        merged = {
            "title": section.title,
            "ref": _merge_refs([c for part in section.parts for c in part.chunks]),
            "key_points": [], "tables": [], "warnings": [], "ai_notes": [],
        }
        succeeded = 0

        for part in section.parts:
            answer = None
            for _ in range(ATTEMPTS_PER_PART):
                try:
                    answer = summarise_part(section.title, part, mode)
                    break
                except llm.LLMError as error:
                    last_error = error.code
                    if error.code in (llm.AI_UNAVAILABLE, llm.AI_MODEL_MISSING):
                        # Asking again cannot help; and if the very first
                        # part fails this way, nothing else will work.
                        if not sections and succeeded == 0 and done == 0:
                            return SummaryResult({}, "FAILED", error.code)
                        break

            if answer is not None:
                succeeded += 1
                if merged["title"] is None:
                    merged["title"] = answer["title"] or None
                for key in ("key_points", "tables", "warnings", "ai_notes"):
                    merged[key].extend(answer[key])

            done += 1
            if on_progress is not None and on_progress(done, total) is False:
                return SummaryResult({}, "FAILED", CANCELLED)

        if merged["title"] is None:
            merged["title"] = f"بخش {number}"

        coverage.append({
            "title": merged["title"],
            "ref": merged["ref"],
            "parts": len(section.parts),
            "done": succeeded,
            "status": (
                "COMPLETE" if succeeded == len(section.parts)
                else "PARTIAL" if succeeded else "MISSING"
            ),
        })
        if succeeded:
            sections.append(merged)

    if not sections:
        return SummaryResult({}, "FAILED", last_error or llm.AI_FAILED)

    overview = ""
    for _ in range(ATTEMPTS_PER_PART):
        try:
            overview = write_overview(sections)
            if overview:
                break
        except llm.LLMError:
            pass

    outline = build_outline(chunks)
    if not outline:
        # No headings in the source: the outline is the list of sections.
        outline = [
            {"title": s["title"], "ref": s["ref"], "children": []}
            for s in sections
        ]

    content = {
        "version": 1,
        "mode": mode,
        "model": llm.model_name(),
        "overview": overview,
        "outline": outline,
        "sections": sections,
        "coverage": coverage,
    }

    complete = all(item["status"] == "COMPLETE" for item in coverage)
    if complete:
        return SummaryResult(content, "READY", None)
    return SummaryResult(content, "NEEDS_REVIEW", INCOMPLETE)
