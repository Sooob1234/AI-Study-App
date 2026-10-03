from fastapi import FastAPI

from app.api.projects import router as projects_router
from app.core.database import Base, engine
from app.models.project import ProjectDB

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI Study App API",
    version="0.1.0"
)

app.include_router(projects_router)


@app.get("/")
def root():
    return {
        "message": "AI Study App backend is running"
    }
