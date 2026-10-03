# AI Study App

Backend of a mobile AI study app: the user adds learning sources (PDF, YouTube,
audio) to a project, picks a goal, and gets an output for that goal.

Current state: projects, sources, PDF upload with page-by-page text extraction,
Persian text clean-up, a quality check, chunking by heading, and user accounts.
No AI yet.

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

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create an account |
| POST | `/auth/login` | Log in; returns a token |
| GET | `/auth/me` | The logged-in user |
| GET / POST | `/projects/` | List / create projects |
| GET | `/projects/{id}` | One project |
| GET / POST | `/projects/{id}/sources/` | List sources / add a non-PDF source |
| POST | `/projects/{id}/sources/pdf` | Upload a PDF (max 50 MB) |
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

## Database changes

The database structure is updated automatically when the app starts
(`app/core/migrate.py`). Each change is a numbered file in
`backend/app/migrations/versions`; existing data is kept.

## PDF processing

upload → store file → extract text per page → clean text → chunk by heading →
quality check → `READY` or `NEEDS_REVIEW`.

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
