"""Checks of the endpoints against a real database (see conftest.py)."""

import os

from tests.pdf_factory import make_pdf

LINE = "This line of plain text fills the page of the test document."

TEXT_PDF = make_pdf([
    ["1- First chapter"] + [f"{LINE} A{i}" for i in range(8)],
    ["2- Second chapter", "2 -1 - A section"] + [f"{LINE} B{i}" for i in range(8)],
])
BLANK_PDF = make_pdf([[], []])


def _project(client, headers, title="Physics"):
    response = client.post("/projects/", json={"title": title}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _disk_path(source_id):
    """Where the stored file of a source is on disk (read from the database)."""
    from app.core.config import to_disk_path
    from app.core.database import SessionLocal
    from app.models.source import SourceDB

    db = SessionLocal()
    try:
        stored = db.query(SourceDB.file_path).filter(SourceDB.id == source_id).scalar()
    finally:
        db.close()

    return to_disk_path(stored)


def _upload(client, headers, project_id, data=TEXT_PDF, name="notes.pdf"):
    return client.post(
        f"/projects/{project_id}/sources/pdf",
        files={"file": (name, data, "application/pdf")},
        headers=headers,
    )


# --- accounts ----------------------------------------------------------------

def test_register_login_and_me(client, new_user):
    headers, user = new_user()
    assert "password" not in user and "password_hash" not in user

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == user["email"]


def test_register_rejects_bad_input(client, new_user):
    _, user = new_user()

    def register(**changes):
        body = {"name": "A", "email": "new@example.com", "password": "long-enough"}
        body.update(changes)
        return client.post("/auth/register", json=body).status_code

    assert register(email=user["email"]) == 409
    assert register(email=user["email"].upper()) == 409
    assert register(email="not-an-email") == 422
    assert register(password="short") == 422
    assert register(name="   ") == 422


def test_login_rejects_wrong_credentials(client, new_user):
    _, user = new_user()

    wrong_password = client.post(
        "/auth/login", data={"username": user["email"], "password": "wrong-one"}
    )
    unknown_email = client.post(
        "/auth/login", data={"username": "nobody@example.com", "password": "x" * 10}
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_everything_needs_a_login(client):
    calls = [
        ("get", "/projects/"),
        ("post", "/projects/"),
        ("get", "/projects/1"),
        ("get", "/projects/1/sources/"),
        ("post", "/projects/1/sources/pdf"),
        ("post", "/projects/1/sources/youtube"),
        ("post", "/projects/1/sources/audio"),
        ("post", "/sources/1/retry"),
        ("get", "/sources/1"),
        ("delete", "/sources/1"),
        ("get", "/sources/1/pages/"),
        ("get", "/sources/1/chunks/"),
        ("post", "/sources/1/chunks/"),
        ("get", "/sources/1/segments/"),
        ("get", "/auth/me"),
    ]

    for method, path in calls:
        assert getattr(client, method)(path).status_code == 401, path

    bad = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/projects/", headers=bad).status_code == 401


# --- projects ----------------------------------------------------------------

def test_project_validation(client, new_user):
    headers, _ = new_user()

    def create(title):
        return client.post("/projects/", json={"title": title}, headers=headers)

    assert create("").status_code == 422
    assert create("   ").status_code == 422
    assert create("x" * 300).status_code == 422
    assert create("  Physics  ").json()["title"] == "Physics"


# --- PDF upload ---------------------------------------------------------------

def test_pdf_upload_extracts_pages_and_chunks(client, new_user):
    headers, _ = new_user()
    project_id = _project(client, headers)

    response = _upload(client, headers, project_id)
    assert response.status_code == 200, response.text
    source = response.json()
    assert source["status"] == "READY"
    assert source["status_detail"] is None
    assert source["page_count"] == 2
    assert "file_path" not in source
    assert os.path.isfile(_disk_path(source["id"]))

    assert client.get(f"/sources/{source['id']}", headers=headers).json() == source

    pages = client.get(f"/sources/{source['id']}/pages/", headers=headers).json()
    assert [page["page_number"] for page in pages] == [1, 2]
    assert "First chapter" in pages[0]["text"]

    chunks = client.get(f"/sources/{source['id']}/chunks/", headers=headers).json()
    assert [chunk["heading"] for chunk in chunks] == [
        "1- First chapter",
        "2- Second chapter › 2 -1 - A section",
    ]
    assert [(c["page_start"], c["page_end"]) for c in chunks] == [(1, 1), (2, 2)]

    assert client.get(
        f"/sources/{source['id']}/segments/", headers=headers
    ).json() == []

    rebuilt = client.post(f"/sources/{source['id']}/chunks/", headers=headers)
    assert rebuilt.json()["chunk_count"] == len(chunks)

    listed = client.get(f"/projects/{project_id}/sources/", headers=headers).json()
    assert [item["id"] for item in listed] == [source["id"]]


def test_pdf_without_text_needs_review(client, new_user):
    headers, _ = new_user()
    project_id = _project(client, headers)

    source = _upload(client, headers, project_id, BLANK_PDF).json()
    assert source["status"] == "NEEDS_REVIEW"
    assert source["status_detail"] == "NO_TEXT"


def test_bad_uploads_are_rejected_and_leave_no_file(client, new_user):
    headers, _ = new_user()
    project_id = _project(client, headers)
    folder = os.path.join(os.environ["UPLOAD_ROOT"], "pdfs")
    before = set(os.listdir(folder))

    assert _upload(client, headers, project_id, b"not a pdf").status_code == 400
    assert _upload(client, headers, project_id, b"").status_code == 400
    assert _upload(client, headers, project_id, name="notes.txt").status_code == 400

    assert set(os.listdir(folder)) == before

    long_name = _upload(client, headers, project_id, name="n" * 300 + ".pdf")
    assert long_name.status_code == 200
    assert len(long_name.json()["title"]) == 255


# --- deleting -----------------------------------------------------------------

def test_delete_source_removes_everything(client, new_user):
    headers, _ = new_user()
    project_id = _project(client, headers)
    source = _upload(client, headers, project_id).json()
    disk_path = _disk_path(source["id"])

    deleted = client.delete(f"/sources/{source['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["file_removed"] is True
    assert not os.path.exists(disk_path)

    assert client.get(f"/sources/{source['id']}", headers=headers).status_code == 404
    assert client.delete(f"/sources/{source['id']}", headers=headers).status_code == 404
    assert client.get(f"/projects/{project_id}/sources/", headers=headers).json() == []
    assert client.get(f"/projects/{project_id}", headers=headers).status_code == 200


# --- ownership ----------------------------------------------------------------

def test_users_cannot_reach_each_others_data(client, new_user):
    owner, _ = new_user()
    stranger, _ = new_user()

    project_id = _project(client, owner)
    source = _upload(client, owner, project_id).json()
    source_id = source["id"]

    assert client.get("/projects/", headers=stranger).json() == []

    blocked = [
        client.get(f"/projects/{project_id}", headers=stranger),
        client.get(f"/projects/{project_id}/sources/", headers=stranger),
        _upload(client, stranger, project_id),
        client.get(f"/sources/{source_id}", headers=stranger),
        client.get(f"/sources/{source_id}/pages/", headers=stranger),
        client.get(f"/sources/{source_id}/chunks/", headers=stranger),
        client.post(f"/sources/{source_id}/chunks/", headers=stranger),
        client.get(f"/sources/{source_id}/segments/", headers=stranger),
        client.post(f"/sources/{source_id}/retry", headers=stranger),
        client.post(
            f"/projects/{project_id}/sources/audio",
            files={"file": ("a.wav", b"x", "audio/wav")},
            headers=stranger,
        ),
        client.delete(f"/sources/{source_id}", headers=stranger),
    ]
    assert [response.status_code for response in blocked] == [404] * len(blocked)

    # Nothing was changed by the attempts.
    assert client.get(f"/sources/{source_id}", headers=owner).status_code == 200
    assert os.path.isfile(_disk_path(source_id))
    listed = client.get(f"/projects/{project_id}/sources/", headers=owner).json()
    assert [item["id"] for item in listed] == [source_id]


# --- YouTube ------------------------------------------------------------------
# YouTube itself is replaced by a stand-in here, so these checks cover
# everything except the real network call.

VIDEO = "https://youtu.be/jNQXAC9IVRw"


def _fake_youtube(monkeypatch, result):
    from app.services import youtube

    def fetch(video_id):
        assert video_id == "jNQXAC9IVRw"
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(youtube, "fetch_youtube", fetch)


def _add_video(client, headers, project_id, url=VIDEO):
    return client.post(
        f"/projects/{project_id}/sources/youtube",
        json={"url": url},
        headers=headers,
    )


def test_youtube_source_is_processed(client, new_user, monkeypatch):
    from app.services.youtube import YouTubeTranscript

    segments = [
        (i * 5.0, i * 5.0 + 5.0, f"spoken sentence number {i} in the lecture " * 3)
        for i in range(40)
    ]
    _fake_youtube(monkeypatch, YouTubeTranscript("A lecture", "en", segments))

    headers, _ = new_user()
    project_id = _project(client, headers)

    response = _add_video(client, headers, project_id)
    assert response.status_code == 200, response.text
    created = response.json()
    # The answer is sent before processing starts.
    assert created["status"] == "PROCESSING"
    assert created["url"] == "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    source = client.get(f"/sources/{created['id']}", headers=headers).json()
    assert source["status"] == "READY"
    assert source["status_detail"] is None
    assert source["title"] == "A lecture"
    assert source["language"] == "en"
    assert source["duration"] == 200
    assert source["source_type"] == "YOUTUBE"

    stored = client.get(f"/sources/{created['id']}/segments/", headers=headers).json()
    assert len(stored) == 40
    assert (stored[1]["start_seconds"], stored[1]["end_seconds"]) == (5.0, 10.0)

    chunks = client.get(f"/sources/{created['id']}/chunks/", headers=headers).json()
    assert len(chunks) > 1
    assert chunks[0]["start_seconds"] == 0.0
    assert chunks[-1]["end_seconds"] == 200.0
    assert chunks[0]["page_start"] is None

    rebuilt = client.post(f"/sources/{created['id']}/chunks/", headers=headers)
    assert rebuilt.json()["chunk_count"] == len(chunks)

    assert client.get(f"/sources/{created['id']}/pages/", headers=headers).json() == []
    assert client.delete(f"/sources/{created['id']}", headers=headers).status_code == 200


def test_youtube_failures_are_reported(client, new_user, monkeypatch):
    from app.services.youtube import YouTubeError, YouTubeTranscript

    headers, _ = new_user()
    project_id = _project(client, headers)

    cases = [
        (YouTubeError("NO_TRANSCRIPT"), "NO_TRANSCRIPT"),
        (YouTubeError("BLOCKED_BY_YOUTUBE"), "BLOCKED_BY_YOUTUBE"),
        (RuntimeError("anything unexpected"), "FETCH_FAILED"),
        (YouTubeTranscript("Silent", "en", [(0.0, 2.0, "   ")]), "NO_TRANSCRIPT"),
    ]

    for result, code in cases:
        _fake_youtube(monkeypatch, result)
        created = _add_video(client, headers, project_id).json()
        source = client.get(f"/sources/{created['id']}", headers=headers).json()

        assert (source["status"], source["status_detail"]) == ("FAILED", code)
        assert client.get(
            f"/sources/{created['id']}/chunks/", headers=headers
        ).json() == []


def test_youtube_link_and_ownership_rules(client, new_user, monkeypatch):
    from app.services.youtube import YouTubeError

    _fake_youtube(monkeypatch, YouTubeError("NO_TRANSCRIPT"))
    owner, _ = new_user()
    stranger, _ = new_user()
    project_id = _project(client, owner)

    assert _add_video(client, owner, project_id, "https://vimeo.com/1").status_code == 400
    assert _add_video(client, owner, project_id, "").status_code == 400
    assert _add_video(client, stranger, project_id).status_code == 404
    assert client.get(f"/projects/{project_id}/sources/", headers=owner).json() == []





def test_strange_input_never_causes_an_internal_error(client, new_user):
    headers, user = new_user()
    huge = "99999999999999999999"

    assert client.post(
        "/projects/", json={"title": "a\u0000b"}, headers=headers
    ).status_code == 422
    assert client.post(
        "/auth/register",
        json={"name": "a\u0000b", "email": "nul@example.com", "password": "long-enough"},
    ).status_code == 422
    assert client.post(
        "/auth/login", data={"username": "a\x00b@example.com", "password": "x" * 10}
    ).status_code == 401

    for path in (f"/projects/{huge}", f"/sources/{huge}", f"/sources/{huge}/pages/", "/projects/0"):
        assert client.get(path, headers=headers).status_code == 422, path
    assert client.delete(f"/sources/{huge}", headers=headers).status_code == 422


def test_oversized_upload_is_refused_before_it_is_stored(client, new_user):
    from app.core.limits import MAX_PDF_SIZE_BYTES

    headers, _ = new_user()
    project_id = _project(client, headers)
    folder = os.path.join(os.environ["UPLOAD_ROOT"], "pdfs")
    before = set(os.listdir(folder))

    response = _upload(
        client, headers, project_id, b"%PDF-1.4\n" + b"0" * (MAX_PDF_SIZE_BYTES + 2_000_000)
    )

    assert response.status_code == 413
    assert set(os.listdir(folder)) == before


def test_password_protected_pdf_gets_a_clear_message(client, new_user):
    import io

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(TEXT_PDF)).pages:
        writer.add_page(page)
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)

    headers, _ = new_user()
    response = _upload(client, headers, _project(client, headers), buffer.getvalue())

    assert response.status_code == 400
    assert "Password-protected" in response.json()["detail"]


def test_stored_file_outside_the_uploads_folder_is_never_removed(app, tmp_path):
    from app.api.sources import _remove_stored_file

    outside = tmp_path / "keep-me.txt"
    outside.write_text("important")

    inside = os.path.join(os.environ["UPLOAD_ROOT"], "pdfs", "remove-me.pdf")
    with open(inside, "w") as handle:
        handle.write("x")

    assert _remove_stored_file(str(outside)) is False
    assert _remove_stored_file(os.path.join(os.environ["UPLOAD_ROOT"], "..", outside.name)) is False
    assert _remove_stored_file(None) is False
    assert outside.read_text() == "important"

    assert _remove_stored_file(inside) is True
    assert not os.path.exists(inside)


def test_first_account_takes_over_rows_without_an_owner(client, new_user):
    from app.api.auth import adopt_ownerless_rows
    from app.core.database import SessionLocal
    from app.models.project import ProjectDB
    from app.models.source import SourceDB

    headers, user = new_user()
    others, _ = new_user()
    other_project = _project(client, others, "Not mine")

    db = SessionLocal()
    try:
        project = ProjectDB(title="From before accounts")
        source = SourceDB(title="old", source_type="PDF", status="READY")
        db.add_all([project, source])
        db.commit()

        assert client.get(f"/projects/{project.id}", headers=headers).status_code == 404

        adopt_ownerless_rows(db, user["id"])
        db.commit()

        assert client.get(f"/projects/{project.id}", headers=headers).status_code == 200
        assert client.get(f"/sources/{source.id}", headers=headers).status_code == 200
        # Rows that already have an owner are left alone.
        assert client.get(f"/projects/{other_project}", headers=headers).status_code == 404
        assert client.get(f"/projects/{other_project}", headers=others).status_code == 200
    finally:
        db.close()


# --- audio --------------------------------------------------------------------
# The speech recogniser is replaced by a stand-in here; reading the audio
# file itself is real. These checks need the optional audio packages.

def _wav(seconds=2.0):
    import io
    import math
    import struct
    import wave

    rate = 8000
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(rate * seconds))
        ))
    return buffer.getvalue()


def _audio_ready():
    import pytest

    from app.services import transcription

    if not transcription.is_available():
        pytest.skip("the optional audio packages are not installed")


def _fake_transcriber(monkeypatch, result):
    from app.services import transcription

    calls = []

    def transcribe(path, language=None):
        calls.append((path, language))
        assert os.path.isfile(path)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(transcription, "transcribe", transcribe)
    return calls


def _upload_audio(client, headers, project_id, data=None, name="lecture.wav", language=None):
    return client.post(
        f"/projects/{project_id}/sources/audio",
        files={"file": (name, _wav() if data is None else data, "audio/wav")},
        data={} if language is None else {"language": language},
        headers=headers,
    )


def test_audio_source_is_transcribed(client, new_user, monkeypatch):
    from app.services.transcription import Transcript

    _audio_ready()
    segments = [
        (i * 5.0, i * 5.0 + 5.0, f"a spoken sentence number {i} of the class " * 3)
        for i in range(40)
    ]
    calls = _fake_transcriber(monkeypatch, Transcript("en", segments))

    headers, _ = new_user()
    project_id = _project(client, headers)

    response = _upload_audio(client, headers, project_id)
    assert response.status_code == 200, response.text
    created = response.json()
    # The answer is sent before the transcription starts.
    assert created["status"] == "PROCESSING"
    assert created["source_type"] == "AUDIO"
    assert created["duration"] == 2
    assert created["title"] == "lecture.wav"
    assert created["language"] is None
    assert [language for _, language in calls] == [None]

    source = client.get(f"/sources/{created['id']}", headers=headers).json()
    assert (source["status"], source["status_detail"]) == ("READY", None)
    # No language was given, so the one the recogniser detected is kept.
    assert source["language"] == "en"

    stored = client.get(f"/sources/{created['id']}/segments/", headers=headers).json()
    assert len(stored) == 40

    chunks = client.get(f"/sources/{created['id']}/chunks/", headers=headers).json()
    assert len(chunks) > 1
    assert (chunks[0]["start_seconds"], chunks[-1]["end_seconds"]) == (0.0, 200.0)
    assert chunks[0]["page_start"] is None

    disk_path = _disk_path(created["id"])
    assert os.path.isfile(disk_path)
    assert client.delete(f"/sources/{created['id']}", headers=headers).json()["file_removed"] is True
    assert not os.path.exists(disk_path)


def test_audio_failures_are_reported_and_can_be_retried(client, new_user, monkeypatch):
    from app.services.transcription import Transcript, TranscriptionError

    _audio_ready()
    headers, _ = new_user()
    project_id = _project(client, headers)

    cases = [
        (TranscriptionError("TRANSCRIBER_UNAVAILABLE"), "TRANSCRIBER_UNAVAILABLE"),
        (RuntimeError("anything unexpected"), "TRANSCRIPTION_FAILED"),
        (Transcript("en", [(0.0, 2.0, "  ")]), "NO_SPEECH"),
        (Transcript("en", []), "NO_SPEECH"),
    ]

    for result, code in cases:
        _fake_transcriber(monkeypatch, result)
        created = _upload_audio(client, headers, project_id).json()
        source = client.get(f"/sources/{created['id']}", headers=headers).json()
        assert (source["status"], source["status_detail"]) == ("FAILED", code)

    # The file was kept, so the same source can be processed again.
    text = "now the recogniser works and the lecture is written down " * 3
    _fake_transcriber(monkeypatch, Transcript("en", [(0.0, 2.0, text)]))

    retried = client.post(f"/sources/{created['id']}/retry", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "PROCESSING"

    source = client.get(f"/sources/{created['id']}", headers=headers).json()
    assert (source["status"], source["status_detail"]) == ("READY", None)

    # Only a failed audio source can be retried.
    assert client.post(f"/sources/{created['id']}/retry", headers=headers).status_code == 400
    pdf = _upload(client, headers, project_id).json()
    assert client.post(f"/sources/{pdf['id']}/retry", headers=headers).status_code == 400


def test_bad_audio_uploads_are_rejected_and_leave_no_file(client, new_user, monkeypatch):
    from app.services.transcription import Transcript

    _audio_ready()
    calls = _fake_transcriber(monkeypatch, Transcript("en", []))
    headers, _ = new_user()
    project_id = _project(client, headers)
    folder = os.path.join(os.environ["UPLOAD_ROOT"], "audio")
    before = set(os.listdir(folder))

    assert _upload_audio(client, headers, project_id, b"not audio at all").status_code == 400
    assert _upload_audio(client, headers, project_id, b"").status_code == 400
    assert _upload_audio(client, headers, project_id, TEXT_PDF, "notes.mp3").status_code == 400
    assert _upload_audio(client, headers, project_id, name="lecture.exe").status_code == 400
    assert _upload_audio(client, headers, project_id, name="lecture").status_code == 400

    assert set(os.listdir(folder)) == before
    assert calls == []
    assert client.get(f"/projects/{project_id}/sources/", headers=headers).json() == []


def test_audio_is_refused_when_the_recogniser_is_not_installed(client, new_user, monkeypatch):
    from app.services import transcription

    monkeypatch.setattr(transcription, "is_available", lambda: False)
    headers, _ = new_user()
    project_id = _project(client, headers)

    response = _upload_audio(client, headers, project_id, b"x")
    assert response.status_code == 503
    assert client.get(f"/projects/{project_id}/sources/", headers=headers).json() == []


def test_source_cut_off_by_a_restart_is_marked_failed(client, new_user, monkeypatch):
    from app.core.database import SessionLocal
    from app.core.recovery import fail_interrupted_sources
    from app.models.source import SourceDB
    from app.services.transcription import Transcript

    _audio_ready()
    text = "the lecture is written down by the recogniser " * 3
    _fake_transcriber(monkeypatch, Transcript("en", [(0.0, 2.0, text)]))
    headers, _ = new_user()
    project_id = _project(client, headers)
    audio = _upload_audio(client, headers, project_id).json()
    pdf = _upload(client, headers, project_id).json()

    # Put the audio back to the state a restart would leave it in.
    db = SessionLocal()
    db.query(SourceDB).filter(SourceDB.id == audio["id"]).update(
        {"status": "PROCESSING", "status_detail": None}
    )
    db.commit()
    db.close()

    assert fail_interrupted_sources() == 1

    after = client.get(f"/sources/{audio['id']}", headers=headers).json()
    assert (after["status"], after["status_detail"]) == ("FAILED", "INTERRUPTED")
    assert client.get(f"/sources/{pdf['id']}", headers=headers).json()["status"] == "READY"

    # An interrupted source can be picked up again.
    assert client.post(f"/sources/{audio['id']}/retry", headers=headers).status_code == 200
    assert client.get(f"/sources/{audio['id']}", headers=headers).json()["status"] == "READY"


def test_the_recogniser_can_read_an_audio_file(tmp_path):
    """The recogniser's own audio reading, without the recognition model.

    Guards against an audio library version that the recogniser cannot use.
    """
    import pytest

    from app.services import transcription

    if not transcription.is_available():
        pytest.skip("the optional audio packages are not installed")

    from faster_whisper.audio import decode_audio

    path = tmp_path / "tone.wav"
    path.write_bytes(_wav(seconds=2.0))

    samples = decode_audio(str(path))

    # Two seconds at the recogniser's own rate of 16000 samples a second.
    assert abs(len(samples) - 32000) < 1600
    assert transcription.probe_audio(str(path)) == pytest.approx(2.0, abs=0.05)


def test_audio_language_is_passed_to_the_recogniser_and_kept_for_retry(client, new_user, monkeypatch):
    from app.services.transcription import Transcript, TranscriptionError

    _audio_ready()
    headers, _ = new_user()
    project_id = _project(client, headers)

    calls = _fake_transcriber(monkeypatch, TranscriptionError("TRANSCRIPTION_FAILED"))
    created = _upload_audio(client, headers, project_id, language=" FA ").json()
    assert created["language"] == "fa"

    text = "درس امروز درباره تاریخ ایران است و برای همه مهم است " * 3
    calls = _fake_transcriber(monkeypatch, Transcript("en", [(0.0, 2.0, text)]))
    assert client.post(f"/sources/{created['id']}/retry", headers=headers).status_code == 200
    assert [language for _, language in calls] == ["fa"]

    source = client.get(f"/sources/{created['id']}", headers=headers).json()
    # The chosen language is not replaced by what the recogniser reports.
    assert (source["status"], source["language"]) == ("READY", "fa")

    for bad in ("persian", "xx", "f a"):
        assert _upload_audio(client, headers, project_id, language=bad).status_code == 400, bad


def test_audio_is_refused_while_the_waiting_line_is_full(client, new_user, monkeypatch):
    from app.core import worker

    _audio_ready()
    monkeypatch.setattr(worker.speech, "has_room", lambda: False)
    headers, _ = new_user()
    project_id = _project(client, headers)
    folder = os.path.join(os.environ["UPLOAD_ROOT"], "audio")
    before = set(os.listdir(folder))

    assert _upload_audio(client, headers, project_id).status_code == 503
    assert set(os.listdir(folder)) == before


def test_youtube_transcript_sent_by_the_app_needs_no_fetch(client, new_user, monkeypatch):
    from app.services import youtube

    def must_not_be_called(video_id):
        raise AssertionError("the server contacted YouTube")

    monkeypatch.setattr(youtube, "fetch_youtube", must_not_be_called)

    headers, _ = new_user()
    project_id = _project(client, headers)
    sentence = "در این بخش درباره تاریخ ایران و اهمیت آن برای دانشجویان صحبت می شود "
    # Sent out of order on purpose; the server puts them in time order.
    segments = [
        {"start": i * 6.0, "duration": 6.0, "text": sentence * 2}
        for i in reversed(range(30))
    ] + [{"start": 500.0, "duration": 1.0, "text": "   "}]

    response = client.post(
        f"/projects/{project_id}/sources/youtube",
        json={
            "url": VIDEO,
            "title": "  درس تاریخ  ",
            "language": "FA",
            "segments": segments,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    source = response.json()
    # The answer already carries the final result.
    assert (source["status"], source["status_detail"]) == ("READY", None)
    assert (source["title"], source["language"], source["duration"]) == ("درس تاریخ", "fa", 180)

    stored = client.get(f"/sources/{source['id']}/segments/", headers=headers).json()
    assert [s["start_seconds"] for s in stored] == [i * 6.0 for i in range(30)]

    chunks = client.get(f"/sources/{source['id']}/chunks/", headers=headers).json()
    assert len(chunks) > 1
    assert (chunks[0]["start_seconds"], chunks[-1]["end_seconds"]) == (0.0, 180.0)


def test_youtube_transcript_sent_by_the_app_is_validated(client, new_user, monkeypatch):
    from app.services.youtube import YouTubeError

    _fake_youtube(monkeypatch, YouTubeError("NO_TRANSCRIPT"))
    headers, _ = new_user()
    project_id = _project(client, headers)

    def add(**body):
        body.setdefault("url", VIDEO)
        return client.post(
            f"/projects/{project_id}/sources/youtube", json=body, headers=headers
        ).status_code

    ok = {"start": 0, "duration": 2, "text": "hello"}
    assert add(segments=[]) == 400
    assert add(segments=[{"start": 0, "duration": 2, "text": "  "}]) == 400
    assert add(segments=[{**ok, "start": -1}]) == 422
    assert add(segments=[{**ok, "duration": -1}]) == 422
    assert add(segments=[{**ok, "text": "x" * 2001}]) == 422
    assert add(segments=[{"start": 0, "text": "no duration"}]) == 422
    assert add(segments=[ok], language="persian language") == 422
    assert add(segments=[ok], title="a\u0000b") == 422
    assert add(segments=[ok], url="https://vimeo.com/1") == 400
    assert add(segments=[ok] * 20001) == 422

    # None of the refused requests left a source behind.
    assert client.get(f"/projects/{project_id}/sources/", headers=headers).json() == []


def test_failed_youtube_source_can_be_retried(client, new_user, monkeypatch):
    from app.services.youtube import YouTubeError, YouTubeTranscript

    headers, _ = new_user()
    project_id = _project(client, headers)

    _fake_youtube(monkeypatch, YouTubeError("BLOCKED_BY_YOUTUBE"))
    created = _add_video(client, headers, project_id).json()
    source = client.get(f"/sources/{created['id']}", headers=headers).json()
    assert (source["status"], source["status_detail"]) == ("FAILED", "BLOCKED_BY_YOUTUBE")

    text = "a sentence spoken in the lecture about the topic " * 3
    _fake_youtube(monkeypatch, YouTubeTranscript("Lecture", "en", [(0.0, 5.0, text)]))
    retried = client.post(f"/sources/{created['id']}/retry", headers=headers)
    assert (retried.status_code, retried.json()["status"]) == (200, "PROCESSING")

    source = client.get(f"/sources/{created['id']}", headers=headers).json()
    assert (source["status"], source["title"]) == ("READY", "Lecture")
    assert client.post(f"/sources/{created['id']}/retry", headers=headers).status_code == 400


# --- findings of the second strict review ----------------------------------------

def test_real_audio_length_is_measured_not_trusted(client, new_user, monkeypatch, tmp_path):
    import pytest

    from app.api import audio_upload
    from app.services import transcription
    from app.services.transcription import Transcript

    _audio_ready()

    path = tmp_path / "tone.wav"
    path.write_bytes(_wav(seconds=3.0))
    assert transcription.measure_audio(str(path), 60) == pytest.approx(3.0, abs=0.05)
    with pytest.raises(transcription.TranscriptionError) as error:
        transcription.measure_audio(str(path), 1)
    assert error.value.code == "AUDIO_TOO_LONG"

    # Through the app: a recording longer than allowed is never transcribed,
    # whatever its header says, and the stored length is the measured one.
    calls = _fake_transcriber(monkeypatch, Transcript("en", [(0.0, 2.0, "spoken words here " * 5)]))
    monkeypatch.setattr(transcription, "probe_audio", lambda path: 1.0)
    headers, _ = new_user()
    project_id = _project(client, headers)

    created = _upload_audio(client, headers, project_id, _wav(seconds=3.0)).json()
    assert created["duration"] == 1
    source = client.get(f"/sources/{created['id']}", headers=headers).json()
    assert (source["status"], source["duration"]) == ("READY", 3)

    monkeypatch.setattr(audio_upload, "MAX_AUDIO_HOURS", 2 / 3600)
    created = _upload_audio(client, headers, project_id, _wav(seconds=3.0)).json()
    source = client.get(f"/sources/{created['id']}", headers=headers).json()
    assert (source["status"], source["status_detail"]) == ("FAILED", "AUDIO_TOO_LONG")
    assert len(calls) == 1


def test_a_failed_source_is_claimed_by_only_one_retry(client, new_user, monkeypatch):
    from app.core.database import SessionLocal
    from app.core.processing import claim_failed_source
    from app.services.youtube import YouTubeError

    _fake_youtube(monkeypatch, YouTubeError("BLOCKED_BY_YOUTUBE"))
    headers, _ = new_user()
    created = _add_video(client, headers, _project(client, headers)).json()

    first, second = SessionLocal(), SessionLocal()
    try:
        assert claim_failed_source(first, created["id"]) is True
        assert claim_failed_source(second, created["id"]) is False
    finally:
        first.close()
        second.close()

    assert client.get(f"/sources/{created['id']}", headers=headers).json()["status"] == "PROCESSING"
    # While it is in processing, a retry is refused.
    assert client.post(f"/sources/{created['id']}/retry", headers=headers).status_code == 400


def test_a_job_never_writes_to_a_source_that_is_no_longer_waiting(client, new_user, monkeypatch):
    from app.api.youtube import process_youtube_source
    from app.core.processing import mark_failed
    from app.services.youtube import YouTubeTranscript

    headers, _ = new_user()
    project_id = _project(client, headers)
    text = "a sentence spoken in the lecture about the topic " * 3
    _fake_youtube(monkeypatch, YouTubeTranscript("First", "en", [(0.0, 5.0, text)]))
    created = _add_video(client, headers, project_id).json()
    assert client.get(f"/sources/{created['id']}", headers=headers).json()["status"] == "READY"

    # A second, late job for the same source must change nothing.
    _fake_youtube(monkeypatch, YouTubeTranscript("Second", "en", [(0.0, 9.0, text * 2)]))
    process_youtube_source(created["id"], "jNQXAC9IVRw")
    mark_failed(created["id"], "FETCH_FAILED")

    source = client.get(f"/sources/{created['id']}", headers=headers).json()
    assert (source["status"], source["title"], source["duration"]) == ("READY", "First", 5)
    assert len(client.get(f"/sources/{created['id']}/segments/", headers=headers).json()) == 1

    # A job for a source that was deleted in the meantime does nothing.
    client.delete(f"/sources/{created['id']}", headers=headers)
    process_youtube_source(created["id"], "jNQXAC9IVRw")
    assert client.get(f"/sources/{created['id']}", headers=headers).status_code == 404


def test_source_deleted_while_it_is_being_transcribed(client, new_user, monkeypatch):
    from app.services import transcription
    from app.services.transcription import Transcript

    _audio_ready()
    headers, _ = new_user()
    project_id = _project(client, headers)
    state = {}

    def transcribe(path, language=None):
        # The user deletes the source while the recogniser is at work.
        state["deleted"] = client.delete(
            f"/sources/{state['id']}", headers=headers
        ).status_code
        return Transcript("en", [(0.0, 2.0, "spoken words here " * 5)])

    monkeypatch.setattr(transcription, "transcribe", transcribe)
    real_measure = transcription.measure_audio

    def measure(path, limit):
        state["id"] = max(
            item["id"] for item in
            client.get(f"/projects/{project_id}/sources/", headers=headers).json()
        )
        return real_measure(path, limit)

    monkeypatch.setattr(transcription, "measure_audio", measure)

    response = _upload_audio(client, headers, project_id)
    assert response.status_code == 200
    assert state["deleted"] == 200
    assert client.get(f"/sources/{state['id']}", headers=headers).status_code == 404
    assert client.get(f"/sources/{state['id']}/segments/", headers=headers).status_code == 404


def test_a_user_can_have_only_a_few_sources_in_processing(client, new_user, monkeypatch):
    from app.core.database import SessionLocal
    from app.core.limits import MAX_PROCESSING_PER_USER
    from app.models.source import SourceDB
    from app.services.youtube import YouTubeError

    _fake_youtube(monkeypatch, YouTubeError("BLOCKED_BY_YOUTUBE"))
    headers, user = new_user()
    other, _ = new_user()
    project_id = _project(client, headers)

    ids = [_add_video(client, headers, project_id).json()["id"] for _ in range(MAX_PROCESSING_PER_USER)]
    db = SessionLocal()
    db.query(SourceDB).filter(SourceDB.id.in_(ids)).update({"status": "PROCESSING"})
    db.commit()
    db.close()

    assert _add_video(client, headers, project_id).status_code == 429
    # Sending the transcript itself needs no processing, so it is allowed.
    with_text = client.post(
        f"/projects/{project_id}/sources/youtube",
        json={"url": VIDEO, "segments": [{"start": 0, "duration": 2, "text": "hello there " * 5}]},
        headers=headers,
    )
    assert with_text.status_code == 200
    # Another user is not affected.
    assert _add_video(client, other, _project(client, other)).status_code == 200


def test_file_names_with_control_characters_are_accepted(client, new_user):
    headers, _ = new_user()
    project_id = _project(client, headers)

    # (The test client escapes the character on the way; the cleaning itself
    # is checked in test_a_title_is_made_from_any_file_name.)
    response = _upload(client, headers, project_id, name="notes\x07 one.pdf")
    assert response.status_code == 200
    assert "\x07" not in response.json()["title"]

    assert client.post(
        f"/projects/{project_id}/sources/youtube", json={"url": "http://["}, headers=headers
    ).status_code == 400


def test_oversized_upload_without_login_is_refused(client):
    response = client.post(
        "/projects/1/sources/audio",
        files={"file": ("a.wav", b"0" * 3_000_000, "audio/wav")},
    )
    assert response.status_code == 401


def test_jobs_really_run_in_the_background(client, new_user, monkeypatch):
    import threading
    import time

    from app.core import worker
    from app.services import transcription
    from app.services.transcription import Transcript

    _audio_ready()
    monkeypatch.setattr(worker, "_INLINE", False)
    release = threading.Event()

    def transcribe(path, language=None):
        release.wait(timeout=10)
        return Transcript("en", [(0.0, 2.0, "spoken words here " * 5)])

    monkeypatch.setattr(transcription, "transcribe", transcribe)
    headers, _ = new_user()
    project_id = _project(client, headers)

    created = _upload_audio(client, headers, project_id).json()
    # The job is still running, and the app keeps answering meanwhile.
    assert client.get(f"/sources/{created['id']}", headers=headers).json()["status"] == "PROCESSING"
    assert client.post(f"/sources/{created['id']}/retry", headers=headers).status_code == 400

    release.set()
    worker.speech.wait_until_empty()
    for _ in range(50):
        source = client.get(f"/sources/{created['id']}", headers=headers).json()
        if source["status"] != "PROCESSING":
            break
        time.sleep(0.1)
    assert source["status"] == "READY"


def test_the_prototype_page_is_served_without_login(client):
    response = client.get("/prototype")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'dir="rtl"' in response.text
    # It is a test tool, not part of the documented interface.
    assert "/prototype" not in client.get("/openapi.json").json()["paths"]
