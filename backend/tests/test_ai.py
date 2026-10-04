"""Checks of the AI layer with a stand-in for the model. No database."""

import pytest

from app.ai import llm, summary
from app.ai.summary import ChunkIn, build_outline, build_summary, plan_sections


def _chunk(heading, text, page=None, start=None):
    if page is not None:
        return ChunkIn(heading=heading, text=text, page_start=page, page_end=page)
    return ChunkIn(heading=heading, text=text, start_seconds=start, end_seconds=start + 60)


BOOK = [
    _chunk("1- فصل اول", "متن آغاز فصل اول " * 20, page=1),
    _chunk("1- فصل اول › 1 -1 - بخش یک", "متن بخش یک " * 20, page=2),
    _chunk("1- فصل اول › 1 -2- بخش دو", "متن بخش دو " * 20, page=3),
    _chunk("2- فصل دوم", "متن فصل دوم " * 20, page=4),
]


def _fake_model(monkeypatch, answer):
    calls = []

    def chat_json(system, user):
        calls.append((system, user))
        result = answer(system, user) if callable(answer) else answer
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(llm, "chat_json", chat_json)
    return calls


def _good(system, user):
    if '"overview"' in system:
        return {"overview": "این منبع دو فصل دارد."}
    return {
        "title": "عنوان ساختگی",
        "key_points": [{"text": "نکته از تکه یک", "part": 1}, {"text": "نکته از تکه دو", "part": 2}],
        "tables": [{"title": "مقایسه", "columns": ["نادرست", "درست"], "rows": [["الف", "ب"], ["پ"]], "part": 1}],
        "warnings": [{"text": "هشدار", "part": 99}],
        "ai_notes": ["توضیح اضافه"],
    }


# --- reading the model's answer ------------------------------------------------

def test_json_is_read_from_a_fenced_or_wrapped_answer():
    assert llm.parse_json_answer('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json_answer('Here it is: {"a": {"b": 2}} done') == {"a": {"b": 2}}

    for bad in ("", "no json here", "[1, 2]", '{"a": ', "```json\n```"):
        with pytest.raises(llm.LLMError) as error:
            llm.parse_json_answer(bad)
        assert error.value.code == llm.AI_BAD_ANSWER


class _Response:
    def __init__(self, status, content=None, text=""):
        self.status_code = status
        self._content = content
        self.text = text

    def json(self):
        if self._content is None:
            raise ValueError("not json")
        return {"choices": [{"message": {"content": self._content}}]}


def test_model_errors_are_mapped_to_reasons(monkeypatch):
    import requests

    def raising(error):
        def post(*args, **kwargs):
            raise error
        return post

    monkeypatch.setattr(requests, "post", raising(requests.ConnectionError()))
    with pytest.raises(llm.LLMError) as error:
        llm.chat_json("s", "u")
    assert error.value.code == llm.AI_UNAVAILABLE

    monkeypatch.setattr(requests, "post", raising(requests.Timeout()))
    with pytest.raises(llm.LLMError) as error:
        llm.chat_json("s", "u")
    assert error.value.code == llm.AI_FAILED

    for status, code in ((404, llm.AI_MODEL_MISSING), (500, llm.AI_FAILED)):
        monkeypatch.setattr(requests, "post", lambda *a, _s=status, **k: _Response(_s))
        with pytest.raises(llm.LLMError) as error:
            llm.chat_json("s", "u")
        assert error.value.code == code

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response(200, "not json"))
    with pytest.raises(llm.LLMError) as error:
        llm.chat_json("s", "u")
    assert error.value.code == llm.AI_BAD_ANSWER


def test_a_service_without_json_mode_is_asked_again_without_it(monkeypatch):
    import requests

    bodies = []

    def post(url, headers=None, json=None, timeout=None):
        bodies.append(dict(json))
        if "response_format" in json:
            return _Response(400)
        return _Response(200, '```json\n{"ok": true}\n```')

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setenv("AI_BASE_URL", "http://example.test/v1/")
    monkeypatch.setenv("AI_MODEL", "some-model")

    assert llm.chat_json("s", "u") == {"ok": True}
    assert ["response_format" in body for body in bodies] == [True, False]
    assert bodies[0]["model"] == "some-model"
    assert llm.base_url() == "http://example.test/v1"


def test_the_api_key_is_sent_only_when_set(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    assert "Authorization" not in llm._headers()

    monkeypatch.setenv("AI_API_KEY", " secret ")
    assert llm._headers()["Authorization"] == "Bearer secret"


# --- planning -------------------------------------------------------------------

def test_sections_follow_chapters_and_parts_stay_small(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_CHARS", "300")
    plan = plan_sections(BOOK)

    assert [section.title for section in plan] == ["1- فصل اول", "2- فصل دوم"]
    assert [len(section.parts) for section in plan] == [3, 1]
    # Every chunk is in exactly one part, in order.
    assert [c for s in plan for p in s.parts for c in p.chunks] == BOOK

    monkeypatch.setenv("AI_MAX_INPUT_CHARS", "100000")
    assert [len(section.parts) for section in plan_sections(BOOK)] == [1, 1]


def test_a_source_without_headings_gets_one_section_per_part(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_CHARS", "500")
    talk = [_chunk(None, "گفتار " * 60, start=i * 60.0) for i in range(3)]
    plan = plan_sections(talk)

    assert [section.title for section in plan] == [None, None, None]
    assert [len(section.parts) for section in plan] == [1, 1, 1]


def test_outline_is_the_tree_of_headings():
    assert build_outline(BOOK) == [
        {
            "title": "1- فصل اول",
            "ref": {"page_start": 1, "page_end": 3},
            "children": [
                {"title": "1 -1 - بخش یک", "ref": {"page_start": 2, "page_end": 2}},
                {"title": "1 -2- بخش دو", "ref": {"page_start": 3, "page_end": 3}},
            ],
        },
        {"title": "2- فصل دوم", "ref": {"page_start": 4, "page_end": 4}, "children": []},
    ]
    assert build_outline([_chunk(None, "x", start=0.0)]) == []


# --- the whole run ----------------------------------------------------------------

def test_summary_keeps_references_and_cleans_the_answer(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_CHARS", "100000")
    calls = _fake_model(monkeypatch, _good)
    progress = []

    result = build_summary(BOOK, summary.SOURCE_ONLY, lambda d, t: progress.append((d, t)) or True)

    assert (result.status, result.status_detail) == ("READY", None)
    content = result.content
    assert content["overview"] == "این منبع دو فصل دارد."
    assert [s["title"] for s in content["sections"]] == ["1- فصل اول", "2- فصل دوم"]
    assert progress == [(1, 2), (2, 2)]
    # Two parts and one overview.
    assert len(calls) == 3
    # Every part of the text was shown to the model.
    assert all(chunk.text in calls[0][1] for chunk in BOOK[:3])

    first = content["sections"][0]
    assert first["ref"] == {"page_start": 1, "page_end": 3}
    assert [p["ref"] for p in first["key_points"]] == [
        {"page_start": 1, "page_end": 1},
        {"page_start": 2, "page_end": 2},
    ]
    assert first["key_points"][1]["subheading"] == "1 -1 - بخش یک"
    # A part number that does not exist falls back to the whole part.
    assert first["warnings"][0]["ref"] == {"page_start": 1, "page_end": 3}
    # Short rows are padded to the number of columns.
    assert first["tables"][0]["rows"] == [["الف", "ب"], ["پ", ""]]
    # In SOURCE_ONLY mode nothing from outside the source is kept.
    assert first["ai_notes"] == []
    assert "ai_notes" not in calls[0][0]

    assert content["coverage"] == [
        {"title": "1- فصل اول", "ref": {"page_start": 1, "page_end": 3}, "parts": 1, "done": 1, "status": "COMPLETE"},
        {"title": "2- فصل دوم", "ref": {"page_start": 4, "page_end": 4}, "parts": 1, "done": 1, "status": "COMPLETE"},
    ]
    assert len(content["outline"]) == 2


def test_ai_notes_are_kept_only_in_source_plus_ai_mode(monkeypatch):
    calls = _fake_model(monkeypatch, _good)
    result = build_summary(BOOK[3:], summary.SOURCE_PLUS_AI)

    assert result.content["sections"][0]["ai_notes"] == ["توضیح اضافه"]
    assert "ai_notes" in calls[0][0]
    assert result.content["mode"] == "SOURCE_PLUS_AI"


def test_timed_source_gets_titles_from_the_model_and_time_references(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_CHARS", "500")
    _fake_model(monkeypatch, _good)
    talk = [_chunk(None, "گفتار " * 60, start=i * 60.0) for i in range(2)]

    content = build_summary(talk, summary.SOURCE_ONLY).content

    assert [s["title"] for s in content["sections"]] == ["عنوان ساختگی", "عنوان ساختگی"]
    assert content["sections"][1]["ref"] == {"start_seconds": 60.0, "end_seconds": 120.0}
    assert [node["title"] for node in content["outline"]] == ["عنوان ساختگی", "عنوان ساختگی"]


def test_a_part_that_fails_is_tried_again_and_then_reported(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_CHARS", "300")
    state = {"n": 0}

    def flaky(system, user):
        if '"overview"' in system:
            return {"overview": "خلاصه"}
        state["n"] += 1
        if "بخش دو" in user:
            return {"key_points": []}          # says nothing: not usable
        if state["n"] == 1:
            return llm.LLMError(llm.AI_BAD_ANSWER)   # fails once, then works
        return _good(system, user)

    _fake_model(monkeypatch, flaky)
    result = build_summary(BOOK, summary.SOURCE_ONLY)

    assert (result.status, result.status_detail) == ("NEEDS_REVIEW", "INCOMPLETE")
    assert [(c["done"], c["parts"], c["status"]) for c in result.content["coverage"]] == [
        (2, 3, "PARTIAL"),
        (1, 1, "COMPLETE"),
    ]


def test_unreachable_model_fails_at_once(monkeypatch):
    calls = _fake_model(monkeypatch, llm.LLMError(llm.AI_UNAVAILABLE))
    result = build_summary(BOOK, summary.SOURCE_ONLY)

    assert (result.status, result.status_detail, result.content) == ("FAILED", "AI_UNAVAILABLE", {})
    assert len(calls) == 1


def test_a_model_that_never_answers_usably_fails(monkeypatch):
    _fake_model(monkeypatch, {"nonsense": True})
    result = build_summary(BOOK, summary.SOURCE_ONLY)
    assert (result.status, result.status_detail) == ("FAILED", "AI_BAD_ANSWER")


def test_nothing_to_summarise_and_cancelling(monkeypatch):
    _fake_model(monkeypatch, _good)

    empty = build_summary([_chunk("1- x", "   ", page=1)], summary.SOURCE_ONLY)
    assert (empty.status, empty.status_detail) == ("FAILED", "NOTHING_TO_SUMMARISE")

    cancelled = build_summary(BOOK, summary.SOURCE_ONLY, lambda done, total: False)
    assert (cancelled.status, cancelled.status_detail) == ("FAILED", "CANCELLED")


def test_odd_answers_do_not_break_the_summary(monkeypatch):
    def odd(system, user):
        if '"overview"' in system:
            return {"overview": None}
        return {
            "title": 12,
            "key_points": ["جملهٔ ساده بدون ساختار", {"text": "  با   فاصله  ", "part": "دو"}, 5, None],
            "tables": [
                {"title": "یک ستون", "columns": ["الف"], "rows": [["x"]]},
                {"title": "بدون سطر", "columns": ["الف", "ب"], "rows": []},
                {"title": "خوب", "columns": ["الف", "ب"], "rows": [["1", 2, 3], "not a row"]},
                "not a table",
            ],
            "warnings": "not a list",
        }

    _fake_model(monkeypatch, odd)
    result = build_summary(BOOK[3:], summary.SOURCE_ONLY)
    section = result.content["sections"][0]

    assert result.status == "READY"
    assert result.content["overview"] == ""
    assert [p["text"] for p in section["key_points"]] == ["جملهٔ ساده بدون ساختار", "با فاصله"]
    assert [(t["title"], t["rows"]) for t in section["tables"]] == [("خوب", [["1", "2"]])]
    assert section["warnings"] == []


def test_a_short_title_line_before_the_first_heading_joins_the_first_section(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_CHARS", "100000")
    opener = _chunk(None, "عنوان جزوه", page=1)
    plan = plan_sections([opener] + BOOK)

    assert [section.title for section in plan] == ["1- فصل اول", "2- فصل دوم"]
    assert plan[0].parts[0].chunks[0].text.startswith("عنوان جزوه\nمتن آغاز فصل اول")

    # A source that is nothing but a short line is still summarised.
    assert len(plan_sections([opener])) == 1
