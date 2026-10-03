# AI Study App

Backend of a mobile AI study app: the user adds learning sources (PDF, YouTube,
audio) to a project, picks a goal, and gets an output for that goal.

Current state: projects, sources, PDF upload with page-by-page text extraction,
Persian text clean-up, a quality check, and chunking by heading. No AI yet.

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
| GET / POST | `/projects/` | List / create projects |
| GET | `/projects/{id}` | One project |
| GET / POST | `/projects/{id}/sources/` | List sources / add a non-PDF source |
| POST | `/projects/{id}/sources/pdf` | Upload a PDF (max 50 MB) |
| GET | `/sources/{id}/pages/` | Extracted text, page by page |
| GET | `/sources/{id}/chunks/` | Chunks with page numbers and heading |
| POST | `/sources/{id}/chunks/` | Rebuild chunks from the saved pages |
| DELETE | `/sources/{id}` | Delete a source with its pages, chunks and file |

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
