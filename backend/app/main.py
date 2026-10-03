from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.sources import router as sources_router
from app.api.pdf_upload import router as pdf_upload_router
from app.api.source_pages import router as source_pages_router
from app.api.source_chunks import router as source_chunks_router

from app.core.migrate import run_migrations

from app.models.user import UserDB
from app.models.project import ProjectDB
from app.models.source import SourceDB, project_sources
from app.models.source_page import SourcePageDB
from app.models.source_chunk import SourceChunkDB


# Creates missing tables and applies any new change to the database
# structure. Existing data is kept.
run_migrations()


app = FastAPI(
    title="AI Study App API",
    version="0.1.0"
)


app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(sources_router)
app.include_router(pdf_upload_router)
app.include_router(source_pages_router)
app.include_router(source_chunks_router)


@app.get("/")
def root():
    return {
        "message": "AI Study App backend is running"
    }
