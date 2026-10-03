"""A real check of YouTube sources against the real YouTube.

It is run on GitHub's servers (see .github/workflows/live-checks.yml), which
can reach youtube.com. YouTube often refuses caption requests that come from
data centres; that outcome (BLOCKED_BY_YOUTUBE) is reported, not hidden.
"""

import sys
import time

# Well-known videos that have captions, and one id that does not exist.
VIDEOS = ["jNQXAC9IVRw", "UF8uR6Z6KLc"]
MISSING = "aaaaaaaaaaa"

EXPECTED_WHEN_REFUSED = {"BLOCKED_BY_YOUTUBE"}


def notice(title: str, message: str) -> None:
    message = message.replace("\n", " ")
    print(f"::notice title={title}::{message}", flush=True)


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import youtube

    failed = False

    # 1. The function that talks to YouTube, on its own.
    for video_id in VIDEOS + [MISSING]:
        started = time.time()
        try:
            result = youtube.fetch_youtube(video_id)
            text = " ".join(piece for _, _, piece in result.segments)
            outcome = (
                f"OK title=[{result.title}] language={result.language} "
                f"segments={len(result.segments)} "
                f"last_end={result.segments[-1][1]:.0f}s text=[{text[:200]}]"
            )
            if video_id == MISSING:
                failed = True
        except youtube.YouTubeError as error:
            outcome = f"YouTubeError {error.code}"
            if video_id == MISSING:
                if error.code not in {"VIDEO_UNAVAILABLE"} | EXPECTED_WHEN_REFUSED:
                    failed = True
            elif error.code not in EXPECTED_WHEN_REFUSED:
                failed = True

        notice(f"youtube fetch {video_id}", f"{outcome} ({time.time() - started:.1f}s)")

    notice("youtube title", f"oEmbed title of {VIDEOS[0]}: [{youtube._fetch_title(VIDEOS[0])}]")

    # 2. The whole path through the app.
    client = TestClient(app)
    client.post("/auth/register", json={
        "name": "Live check", "email": "live@example.com", "password": "live-check-pass",
    })
    token = client.post("/auth/login", data={
        "username": "live@example.com", "password": "live-check-pass",
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    project_id = client.post(
        "/projects/", json={"title": "Live"}, headers=headers
    ).json()["id"]

    created = client.post(
        f"/projects/{project_id}/sources/youtube",
        json={"url": f"https://youtu.be/{VIDEOS[0]}?t=3"},
        headers=headers,
    )
    started = time.time()
    while True:
        source = client.get(f"/sources/{created.json()['id']}", headers=headers).json()
        if source["status"] != "PROCESSING" or time.time() - started > 120:
            break
        time.sleep(1)

    chunks = client.get(f"/sources/{source['id']}/chunks/", headers=headers).json()
    notice(
        "youtube through the app",
        f"status={source['status']} detail={source['status_detail']} "
        f"title=[{source['title']}] language={source['language']} "
        f"duration={source['duration']} chunks={len(chunks)}",
    )

    if source["status"] == "PROCESSING":
        failed = True
    if source["status"] == "FAILED" and source["status_detail"] not in EXPECTED_WHEN_REFUSED:
        failed = True
    if source["status"] == "READY" and not chunks:
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
