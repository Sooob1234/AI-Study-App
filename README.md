# AI Study App

Backend of a mobile AI study app: the user adds learning sources (PDF, YouTube,
audio) to a project, picks a goal, and gets an output for that goal.

Current state: projects, sources, PDF upload with page-by-page text extraction,
Persian text clean-up, a quality check, chunking by heading, audio sources with
speech-to-text, and user accounts. No AI output generation yet.

## Run

Docker Desktop must be running.

```bash
docker compose up -d                      # PostgreSQL on port 5433
cd backend
cp .env.example .env                      # first time only
python -m venv .venv                      # first time only
source .venv/Scripts/activate             # Windows Git Bash
pip install -r requirements.txt           # first time only
uvicorn app.main:app --reload
```

Swagger UI: http://127.0.0.1:8000/docs

Test page (Persian, for trying PDF, audio and YouTube by hand):
http://127.0.0.1:8000/prototype

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create an account |
| POST | `/auth/login` | Log in; returns a token |
| GET | `/auth/me` | The logged-in user |
| GET / POST | `/projects/` | List / create projects |
| GET | `/projects/{id}` | One project |
| GET | `/projects/{id}/sources/` | List the sources of a project |
| POST | `/projects/{id}/sources/pdf` | Upload a PDF (max 50 MB) |
| POST | `/projects/{id}/sources/youtube` | Add a YouTube video by link |
| POST | `/projects/{id}/sources/audio` | Upload an audio file (max 200 MB, 2 hours) |
| POST | `/sources/{id}/retry` | Process a failed audio or YouTube source again |
| GET | `/sources/{id}` | One source and its processing status |
| GET | `/sources/{id}/pages/` | Extracted text, page by page |
| GET | `/sources/{id}/chunks/` | Chunks with page numbers and heading |
| GET | `/sources/{id}/segments/` | Timed transcript of a video or audio source |
| POST | `/sources/{id}/chunks/` | Rebuild chunks from the saved pages |
| DELETE | `/sources/{id}` | Delete a source with its pages, chunks and file |

All endpoints except register and login need a login, and every user sees
only their own projects and sources. In Swagger: create an account with
`/auth/register`, then press **Authorize** at the top of the page and enter
the email (in the "username" box) and the password.

Projects and sources made before accounts existed are given to the first
account that registers.

## YouTube processing

A YouTube source can be added in two ways.

1. **The app sends the captions.** `POST /projects/{id}/sources/youtube` with
   `url` and `segments` (`start`, `duration`, `text`), optionally `title` and
   `language`. The server does not contact YouTube and answers with the final
   status. This works wherever the server is hosted.
2. **The server fetches the captions.** Only `url` is sent. The source is saved
   as `PROCESSING`, the request is answered, and the captions are fetched in
   the background.

Either way: clean text → timed segments → chunks with a time span → `READY`,
or `FAILED` with a reason in `status_detail` (`NO_TRANSCRIPT`,
`VIDEO_UNAVAILABLE`, `BLOCKED_BY_YOUTUBE`, `FETCH_FAILED`, `INTERRUPTED`). A
failed YouTube source can be retried.

**YouTube refuses requests from data-centre addresses.** Checked from GitHub's
servers: both the captions and the audio of ordinary public videos were
refused (`BLOCKED_BY_YOUTUBE`, "Sign in to confirm you're not a bot"). A server
in a data centre can therefore use way 2 only through a proxy with a
home-connection address, set in `.env` as `YOUTUBE_PROXY_URL`. Way 1 needs no
proxy. Videos without captions cannot be processed yet.

## Audio processing

upload → store file → source saved as `PROCESSING` and the request is
answered → speech is written down in the background → clean text → timed
segments → chunks with a time span → `READY`, or `FAILED` with a reason in
`status_detail` (`NO_SPEECH`, `TRANSCRIPTION_FAILED`, `TRANSCRIBER_UNAVAILABLE`,
`INTERRUPTED`, `SERVER_BUSY`, `AUDIO_TOO_LONG`). A failed audio source can be
retried; its file is kept. Audio files are transcribed one at a time, at most
20 may wait, and one user may have at most 5 sources in processing at once.
The length of a recording is measured from its sound, not read from its header.

Speech is recognised on the server itself by the open Whisper model, so no
outside service, account or payment is needed. This part is optional:

```bash
pip install -r requirements-audio.txt
```

Without it the app runs and answers audio uploads with 503. The first audio
file downloads the model (about 500 MB for the default `small`) from
huggingface.co. `WHISPER_MODEL` in `.env` chooses the model: `tiny`, `base`,
`small`, `medium`, `large-v3` (larger is more accurate and slower).

Send the spoken language with the upload (`language=fa`). Without it the
language is guessed, and a wrong guess gives a useless transcript.

A source that was still `PROCESSING` when the app stopped is marked
`FAILED / INTERRUPTED` at the next start.

## Database changes

The database structure is updated automatically when the app starts
(`app/core/migrate.py`). Each change is a numbered file in
`backend/app/migrations/versions`; existing data is kept.

## PDF processing

upload → store file → extract text per page → clean text → chunk by heading →
quality check → `READY` or `NEEDS_REVIEW`.

A source that is `NEEDS_REVIEW` says why in `status_detail`: `NO_TEXT` (for
example a scanned PDF) or `REVERSED_TEXT` (Persian letters came out mirrored).

Known limits of the extracted text: half-spaces are lost, tables become
consecutive lines, highlights are lost, and there is no OCR. Headings are
recognised only when they are numbered (`3-`, `3 -2-`).

Source processing (`app/services`) is kept separate from AI output generation,
which is not built yet.

## Checks

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

That runs the checks that need no database. To also run the endpoint checks,
create an empty database whose name contains `test` and point
`TEST_DATABASE_URL` at it (the checks erase everything in it):

```bash
TEST_DATABASE_URL=postgresql+psycopg2://ai_study:ai_study_password@localhost:5433/ai_study_test python -m pytest
```

The same checks run on GitHub on every push (`.github/workflows/tests.yml`).
`live-checks.yml` runs the real speech recogniser and a real YouTube check on
GitHub's servers; start it from the Actions tab.

