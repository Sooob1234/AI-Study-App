from fastapi import FastAPI

from app.api.pdf_upload import MAX_PDF_SIZE_BYTES, MAX_PDF_SIZE_MB
from app.core.body_limit import BodySizeLimitMiddleware

from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.sources import router as sources_router
from app.api.pdf_upload import router as pdf_upload_router
from app.api.youtube import fail_interrupted_sources
from app.api.youtube import router as youtube_router
from app.api.source_pages import router as source_pages_router
from app.api.source_chunks import router as source_chunks_router
from app.api.source_segments import router as source_segments_router

from app.core.migrate import run_migrations

from app.models.user import UserDB
from app.models.project import ProjectDB
from app.models.source import SourceDB, project_sources
from app.models.source_page import SourcePageDB
from app.models.source_chunk import SourceChunkDB
from app.models.source_segment import SourceSegmentDB


# Creates missing tables and applies any new change to the database
# structure. Existing data is kept.
run_migrations()

# A video that was being processed when the app last stopped cannot finish.
fail_interrupted_sources()


app = FastAPI(
    title="AI Study App API",
    version="0.1.0"
)


# Nothing larger than the biggest allowed PDF (plus a little room for the
# form around it) is read from the network at all.
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=MAX_PDF_SIZE_BYTES + 1024 * 1024,
    detail=f"Request is larger than {MAX_PDF_SIZE_MB} MB",
)

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(sources_router)
app.include_router(pdf_upload_router)
app.include_router(youtube_router)
app.include_router(source_pages_router)
app.include_router(source_chunks_router)
app.include_router(source_segments_router)


@app.get("/")
def root():
    return {
        "message": "AI Study App backend is running"
    }
