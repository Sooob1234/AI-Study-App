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


# --- findings of the strict review ---------------------------------------------

def test_tokens_that_are_expired_or_wrongly_signed_are_refused(client, new_user):
    from datetime import datetime, timedelta, timezone

    import jwt

    from app.core.config import SECRET_KEY

    _, user = new_user()
    now = datetime.now(timezone.utc)

    def token(secret=SECRET_KEY, algorithm="HS256", **changes):
        payload = {"sub": str(user["id"]), "exp": now + timedelta(hours=1)}
        payload.update(changes)
        return jwt.encode(payload, secret, algorithm=algorithm)

    def status(value):
        return client.get(
            "/auth/me", headers={"Authorization": f"Bearer {value}"}
        ).status_code

    assert status(token()) == 200
    assert status(token(exp=now - timedelta(minutes=1))) == 401
    assert status(token(secret="another-key-of-sufficient-length-000")) == 401
    assert status(token(sub="999999999")) == 401
    assert status(token(sub="not-a-number")) == 401
    # A token with no signature at all.
    assert status(jwt.encode({"sub": str(user["id"])}, None, algorithm="none")) == 401


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
