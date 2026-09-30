import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import PipelineEvent, PipelineRun


router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run_dict(run: PipelineRun) -> dict:
    return {
        "id": str(run.id),
        "external_id": run.external_id,
        "run_key": run.run_key,
        "pipeline": run.pipeline,
        "status": run.status,
        "config": run.config,
        "counters": run.counters,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


@router.get("")
def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict:
    total = session.scalar(select(func.count(PipelineRun.id))) or 0
    runs = session.scalars(
        select(PipelineRun)
        .order_by(PipelineRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": [_run_dict(run) for run in runs], "total": total}


@router.get("/{run_id}")
def run_detail(run_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    events = session.scalars(
        select(PipelineEvent)
        .where(PipelineEvent.pipeline_run_id == run_id)
        .order_by(PipelineEvent.created_at)
    ).all()
    return {
        **_run_dict(run),
        "events": [
            {
                "id": str(event.id),
                "level": event.level,
                "event_type": event.event_type,
                "message": event.message,
                "details": event.details,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }
