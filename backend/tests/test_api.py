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
        ("post", "/projects/1/sources/"),
        ("post", "/projects/1/sources/pdf"),
        ("post", "/projects/1/sources/youtube"),
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
    assert os.path.isfile(source["file_path"])

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


def test_manual_source_rules(client, new_user):
    headers, _ = new_user()
    project_id = _project(client, headers)
    url = f"/projects/{project_id}/sources/"

    def create(**body):
        return client.post(url, json=body, headers=headers)

    assert create(title="v", source_type="PDF").status_code == 400
    assert create(title="v", source_type="YOUTUBE").status_code == 400
    assert create(title="v", source_type="WORD").status_code == 422
    assert create(title="v", source_type="AUDIO", duration=-1).status_code == 422

    made = create(title="v", source_type="AUDIO", file_path="/etc/passwd")
    assert made.status_code == 200
    assert made.json()["file_path"] is None


# --- deleting -----------------------------------------------------------------

def test_delete_source_removes_everything(client, new_user):
    headers, _ = new_user()
    project_id = _project(client, headers)
    source = _upload(client, headers, project_id).json()

    deleted = client.delete(f"/sources/{source['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["file_removed"] is True
    assert not os.path.exists(source["file_path"])

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
        client.post(
            f"/projects/{project_id}/sources/",
            json={"title": "v", "source_type": "AUDIO"},
            headers=stranger,
        ),
        _upload(client, stranger, project_id),
        client.get(f"/sources/{source_id}", headers=stranger),
        client.get(f"/sources/{source_id}/pages/", headers=stranger),
        client.get(f"/sources/{source_id}/chunks/", headers=stranger),
        client.post(f"/sources/{source_id}/chunks/", headers=stranger),
        client.get(f"/sources/{source_id}/segments/", headers=stranger),
        client.delete(f"/sources/{source_id}", headers=stranger),
    ]
    assert [response.status_code for response in blocked] == [404] * len(blocked)

    # Nothing was changed by the attempts.
    assert client.get(f"/sources/{source_id}", headers=owner).status_code == 200
    assert os.path.isfile(source["file_path"])
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


def test_video_cut_off_by_a_restart_is_marked_failed(client, new_user, monkeypatch):
    from app.api.youtube import fail_interrupted_sources
    from app.core.database import SessionLocal
    from app.models.source import SourceDB
    from app.services.youtube import YouTubeError

    _fake_youtube(monkeypatch, YouTubeError("NO_TRANSCRIPT"))
    headers, _ = new_user()
    project_id = _project(client, headers)
    video = _add_video(client, headers, project_id).json()
    audio = client.post(
        f"/projects/{project_id}/sources/",
        json={"title": "v", "source_type": "AUDIO"},
        headers=headers,
    ).json()

    # Put the video back to the state a restart would leave it in.
    db = SessionLocal()
    db.query(SourceDB).filter(SourceDB.id == video["id"]).update(
        {"status": "PROCESSING", "status_detail": None}
    )
    db.commit()
    db.close()

    assert fail_interrupted_sources() == 1

    after = client.get(f"/sources/{video['id']}", headers=headers).json()
    assert (after["status"], after["status_detail"]) == ("FAILED", "INTERRUPTED")
    untouched = client.get(f"/sources/{audio['id']}", headers=headers).json()
    assert untouched["status"] == "PROCESSING"
