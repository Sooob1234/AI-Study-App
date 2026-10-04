from fastapi import FastAPI

from app.core.body_limit import BodySizeLimitMiddleware
from app.core.limits import request_limit_for
from app.core.upload_gate import refuse_before_reading

from app.api.auth import router as auth_router
from app.api.prototype import router as prototype_router
from app.api.projects import router as projects_router
from app.api.sources import router as sources_router
from app.api.pdf_upload import router as pdf_upload_router
from app.api.youtube import router as youtube_router
from app.api.audio_upload import router as audio_upload_router
from app.api.source_retry import router as source_retry_router
from app.api.source_pages import router as source_pages_router
from app.api.source_chunks import router as source_chunks_router
from app.api.source_segments import router as source_segments_router
from app.api.outputs import router as outputs_router

from app.core.migrate import run_migrations
from app.core.recovery import fail_interrupted_sources

from app.models.user import UserDB
from app.models.project import ProjectDB
from app.models.source import SourceDB, project_sources
from app.models.source_page import SourcePageDB
from app.models.source_chunk import SourceChunkDB
from app.models.source_segment import SourceSegmentDB
from app.models.output import OutputDB


# Creates missing tables and applies any new change to the database
# structure. Existing data is kept.
run_migrations()

# A source that was being processed when the app last stopped cannot finish.
fail_interrupted_sources()


app = FastAPI(
    title="AI Study App API",
    version="0.1.0"
)


# A request larger than its path allows is refused while it is being read.
app.add_middleware(
    BodySizeLimitMiddleware,
    limit_for=request_limit_for,
    refuse_before_reading=refuse_before_reading,
)

app.include_router(prototype_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(sources_router)
app.include_router(pdf_upload_router)
app.include_router(youtube_router)
app.include_router(audio_upload_router)
app.include_router(source_retry_router)
app.include_router(source_pages_router)
app.include_router(source_chunks_router)
app.include_router(source_segments_router)
app.include_router(outputs_router)


@app.get("/")
def root():
    return {
        "message": "AI Study App backend is running"
    }
