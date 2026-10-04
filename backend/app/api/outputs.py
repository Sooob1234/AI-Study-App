import logging

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.ai import llm
from app.ai.summary import ChunkIn, build_summary
from app.api.deps import get_current_user, get_own_project
from app.core import worker
from app.core.database import SessionLocal, get_db
from app.core.limits import MAX_OUTPUTS_IN_PROCESSING_PER_USER
from app.models.output import (
    OutputCreate,
    OutputDB,
    OutputResponse,
    OutputSummary,
    output_sources,
)
from app.models.project import ProjectDB
from app.models.source import SourceDB, project_sources
from app.models.source_chunk import SourceChunkDB
from app.models.user import UserDB
from app.models.validation import MAX_DB_INTEGER

router = APIRouter(
    tags=["Outputs"]
)

# OUTPUTS_V1

logger = logging.getLogger(__name__)

GOAL_TITLES = {"SUMMARY": "خلاصه"}


def _source_ids(db: Session, output_id: int) -> list[int]:
    return list(db.scalars(
        select(output_sources.c.source_id)
        .where(output_sources.c.output_id == output_id)
        .order_by(output_sources.c.source_id)
    ))


def _as_response(db: Session, output: OutputDB, with_content: bool):
    model = OutputResponse if with_content else OutputSummary
    data = model.model_validate(output)
    data.source_ids = _source_ids(db, output.id)
    return data


def get_own_output(
    output_id: int = Path(ge=1, le=MAX_DB_INTEGER),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> OutputDB:
    output = db.query(OutputDB).filter(
        OutputDB.id == output_id,
        OutputDB.user_id == user.id
    ).first()

    if output is None:
        raise HTTPException(
            status_code=404,
            detail="Output not found"
        )

    return output


def _finish(output_id: int, values: dict) -> None:
    """Store the result on an output that is still waiting for it."""
    db = SessionLocal()
    try:
        db.execute(
            update(OutputDB)
            .where(OutputDB.id == output_id, OutputDB.status == "PROCESSING")
            .values(**values)
        )
        db.commit()
    finally:
        db.close()


def make_summary(output_id: int) -> None:
    """Build the summary for an output. Runs in the background worker.

    It always ends by setting the output to READY, NEEDS_REVIEW or FAILED.
    """
    try:
        _make_summary(output_id)
    except Exception:
        logger.exception("Making output %s failed", output_id)
        try:
            _finish(output_id, {"status": "FAILED", "status_detail": llm.AI_FAILED})
        except Exception:
            logger.exception("Could not record the failure of output %s", output_id)


def _make_summary(output_id: int) -> None:
    # Step 1: read what is needed, and let go of the database.
    db = SessionLocal()
    try:
        output = db.query(OutputDB).filter(
            OutputDB.id == output_id,
            OutputDB.status == "PROCESSING"
        ).first()
        if output is None:
            return
        mode = output.mode

        rows = db.query(SourceChunkDB).filter(
            SourceChunkDB.source_id.in_(_source_ids(db, output_id))
        ).order_by(
            SourceChunkDB.source_id, SourceChunkDB.chunk_index
        ).all()

        chunks = [
            ChunkIn(
                heading=row.heading,
                text=row.text,
                page_start=row.page_start,
                page_end=row.page_end,
                start_seconds=row.start_seconds,
                end_seconds=row.end_seconds,
            )
            for row in rows
        ]
    finally:
        db.close()

    # Step 2: the slow part. Progress is written as it goes, and the run
    # stops if the output has been deleted meanwhile.
    def on_progress(done: int, total: int) -> bool:
        session = SessionLocal()
        try:
            result = session.execute(
                update(OutputDB)
                .where(OutputDB.id == output_id, OutputDB.status == "PROCESSING")
                .values(progress_done=done, progress_total=total)
            )
            session.commit()
            return result.rowcount == 1
        finally:
            session.close()

    result = build_summary(chunks, mode, on_progress)

    # Step 3: store the result.
    _finish(output_id, {
        "status": result.status,
        "status_detail": result.status_detail,
        "content": result.content or None,
    })


@router.post(
    "/projects/{project_id}/outputs/",
    response_model=OutputSummary
)
def create_output(
    data: OutputCreate,
    project: ProjectDB = Depends(get_own_project),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ask for an output. The answer comes back at once with status
    PROCESSING; ask GET /outputs/{id} for the progress and the result."""
    if data.goal_type.value != "SUMMARY":
        raise HTTPException(
            status_code=400,
            detail="Only summaries can be made at the moment"
        )

    if data.scope_type.value != "ONE_SOURCE" or len(data.source_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail="An output can be made from one source at the moment"
        )

    source = db.scalars(
        select(SourceDB)
        .join(project_sources, SourceDB.id == project_sources.c.source_id)
        .where(
            project_sources.c.project_id == project.id,
            SourceDB.id == data.source_ids[0],
            SourceDB.user_id == user.id,
        )
    ).first()

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Source not found"
        )

    if source.status != "READY":
        raise HTTPException(
            status_code=400,
            detail="Only a source that is READY can be summarised"
        )

    in_processing = db.query(OutputDB).filter(
        OutputDB.user_id == user.id,
        OutputDB.status == "PROCESSING"
    ).count()
    if in_processing >= MAX_OUTPUTS_IN_PROCESSING_PER_USER:
        raise HTTPException(
            status_code=429,
            detail="Another of your outputs is still being made; wait for it to finish"
        )

    if not worker.ai.has_room():
        raise HTTPException(
            status_code=503,
            detail="The server is busy making other outputs; try again later"
        )

    output = OutputDB(
        user_id=user.id,
        project_id=project.id,
        title=f"{GOAL_TITLES['SUMMARY']}: {source.title}"[:255],
        goal_type=data.goal_type.value,
        scope_type=data.scope_type.value,
        mode=data.mode.value,
        status="PROCESSING",
        progress_done=0,
        progress_total=0,
    )
    db.add(output)
    db.flush()

    db.execute(
        insert(output_sources).values(output_id=output.id, source_id=source.id)
    )
    db.commit()
    db.refresh(output)

    answer = _as_response(db, output, with_content=False)
    output_id = output.id

    try:
        worker.ai.submit(make_summary, output_id)
    except worker.WorkerBusy:
        _finish(output_id, {"status": "FAILED", "status_detail": "SERVER_BUSY"})
        answer.status, answer.status_detail = "FAILED", "SERVER_BUSY"

    return answer


@router.get(
    "/projects/{project_id}/outputs/",
    response_model=list[OutputSummary]
)
def list_outputs(
    project: ProjectDB = Depends(get_own_project),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    outputs = db.query(OutputDB).filter(
        OutputDB.project_id == project.id,
        OutputDB.user_id == user.id
    ).order_by(OutputDB.id.desc()).all()

    return [_as_response(db, output, with_content=False) for output in outputs]


@router.get("/outputs/{output_id}", response_model=OutputResponse)
def get_output(
    output: OutputDB = Depends(get_own_output),
    db: Session = Depends(get_db)
):
    return _as_response(db, output, with_content=True)


@router.delete("/outputs/{output_id}")
def delete_output(
    output: OutputDB = Depends(get_own_output),
    db: Session = Depends(get_db)
):
    """Delete an output. One that is still being made stops soon after."""
    output_id = output.id

    db.execute(delete(OutputDB).where(OutputDB.id == output_id))
    db.commit()

    return {"deleted_output_id": output_id}


@router.get("/ai/status")
def ai_status(user: UserDB = Depends(get_current_user)):
    """Which AI model the app is set to use, and whether it answers."""
    return {
        "model": llm.model_name(),
        "reachable": llm.is_reachable(),
    }
