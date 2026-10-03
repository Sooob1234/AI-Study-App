"""A real end-to-end check of audio sources, with the real speech recogniser.

It is run on GitHub's servers (see .github/workflows/live-checks.yml), not as
part of the ordinary checks, because it downloads the recognition model.

Speech is produced with the espeak-ng program, uploaded through the app, and
the app's own transcript is compared with what was said.
"""

import os
import subprocess
import sys
import tempfile
import time

ENGLISH = (
    "The mitochondria is the powerhouse of the cell. "
    "Photosynthesis happens in the leaves of green plants. "
    "Water boils at one hundred degrees."
)
ENGLISH_WORDS = ["powerhouse", "cell", "photosynthesis", "plants", "water"]
PERSIAN = "امروز درباره تاریخ ایران صحبت می کنیم. این درس برای همه دانشجویان مهم است."


def notice(title: str, message: str) -> None:
    message = message.replace("\n", " ")
    print(f"::notice title={title}::{message}", flush=True)


def speak(text: str, voice: str, path: str) -> None:
    subprocess.run(
        ["espeak-ng", "-v", voice, "-s", "140", "-w", path, text], check=True
    )


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import transcription

    client = TestClient(app)
    folder = tempfile.mkdtemp()
    failed = False

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

    for name, voice, text in (("english", "en-us", ENGLISH), ("persian", "fa", PERSIAN)):
        path = os.path.join(folder, f"{name}.wav")
        speak(text, voice, path)

        try:
            # Called directly first, so that a failure shows its real cause.
            transcription.transcribe(path)
        except Exception:
            import traceback

            cause = traceback.format_exc()
            if sys.exc_info()[1].__context__ is not None:
                cause = "".join(traceback.format_exception(sys.exc_info()[1].__context__))
            notice(f"audio {name} cause", cause[-900:])

        started = time.time()
        with open(path, "rb") as handle:
            created = client.post(
                f"/projects/{project_id}/sources/audio",
                files={"file": (f"{name}.wav", handle, "audio/wav")},
                headers=headers,
            )
        if created.status_code != 200:
            notice(f"audio {name}", f"UPLOAD FAILED {created.status_code} {created.text}")
            failed = True
            continue

        source = client.get(
            f"/sources/{created.json()['id']}", headers=headers
        ).json()
        segments = client.get(
            f"/sources/{source['id']}/segments/", headers=headers
        ).json()
        chunks = client.get(
            f"/sources/{source['id']}/chunks/", headers=headers
        ).json()
        heard = " ".join(segment["text"] for segment in segments)

        notice(
            f"audio {name}",
            f"model={transcription.MODEL_NAME} status={source['status']} "
            f"detail={source['status_detail']} audio={source['duration']}s "
            f"took={time.time() - started:.0f}s segments={len(segments)} "
            f"chunks={len(chunks)} heard=[{heard}]",
        )

        if name == "english":
            missing = [w for w in ENGLISH_WORDS if w not in heard.lower()]
            if source["status"] != "READY" or missing or not chunks:
                notice("audio english", f"NOT AS EXPECTED, missing words: {missing}")
                failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
