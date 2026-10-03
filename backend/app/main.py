from fastapi import FastAPI

from app.api.projects import router as projects_router
from app.api.sources import router as sources_router
from app.api.pdf_upload import router as pdf_upload_router
from app.api.source_pages import router as source_pages_router

from app.core.database import Base, engine

from app.models.project import ProjectDB
from app.models.source import SourceDB, project_sources
from app.models.source_page import SourcePageDB


Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="AI Study App API",
    version="0.1.0"
)


app.include_router(projects_router)
app.include_router(sources_router)
app.include_router(pdf_upload_router)
app.include_router(source_pages_router)


@app.get("/")
def root():
    return {
        "message": "AI Study App backend is running"
    }
