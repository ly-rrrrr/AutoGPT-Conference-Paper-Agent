import re
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import REPOSITORY_ROOT, get_settings
from app.database import get_session
from app.models import PipelineEvent, PipelineRun
from app.pipeline_adapter import (
    AnalysisStart,
    DockerAnalysisBackend,
    PipelineConflictError,
    PipelineController,
    discover_platform,
)


router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


class AnalysisStartRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    analysis_concurrency: int = Field(ge=1, le=3)
    analysis_request_interval_seconds: int = Field(ge=0, le=300)
    max_new_analyses_per_run: int = Field(ge=0, le=10000)


class MappingStartRequest(BaseModel):
    retry_unresolved: bool = False


@lru_cache
def get_pipeline_controller() -> PipelineController:
    settings = get_settings()
    platform = discover_platform(REPOSITORY_ROOT)
    backend = DockerAnalysisBackend(
        platform, REPOSITORY_ROOT / "scripts" / "console_backend.py"
    )
    return PipelineController(REPOSITORY_ROOT, platform, settings.source_root, backend)


def require_local_action(
    request: Request, x_workbench_request: str | None = Header(default=None)
) -> None:
    host = request.url.hostname
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        raise HTTPException(status_code=403, detail="仅允许本机访问")
    origin = request.headers.get("origin")
    if origin and origin not in {"http://127.0.0.1:8767", "http://localhost:8767"}:
        raise HTTPException(status_code=403, detail="来源不受信任")
    if x_workbench_request != "1":
        raise HTTPException(status_code=403, detail="缺少明确操作标记")


def _record_start(session: Session, result: dict) -> PipelineRun:
    now = datetime.now(UTC)
    run = PipelineRun(
        external_id=result.get("external_id"),
        run_key=result["run_key"],
        pipeline=result["pipeline"],
        status=result["status"],
        config=result.get("config", {}),
        started_at=now,
    )
    session.add(run)
    session.flush()
    session.add(
        PipelineEvent(
            pipeline_run_id=run.id,
            level="INFO",
            event_type=f"{result['pipeline']}_started",
            message=result["message"],
            details={"external_id": result.get("external_id")},
        )
    )
    session.commit()
    return run


@router.get("/status")
def pipeline_status(
    controller: PipelineController = Depends(get_pipeline_controller),
) -> dict:
    return controller.status()


@router.post("/analysis/start", status_code=202, dependencies=[Depends(require_local_action)])
def start_analysis(
    payload: AnalysisStartRequest,
    session: Session = Depends(get_session),
    controller: PipelineController = Depends(get_pipeline_controller),
) -> dict:
    try:
        result = controller.start_analysis(AnalysisStart(**payload.model_dump()))
    except PipelineConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    run = _record_start(session, result)
    return {**result, "id": str(run.id)}


@router.post("/analysis/stop", dependencies=[Depends(require_local_action)])
def stop_analysis(
    controller: PipelineController = Depends(get_pipeline_controller),
) -> dict:
    return controller.stop_analysis()


@router.post("/mapping/start", status_code=202, dependencies=[Depends(require_local_action)])
def start_mapping(
    payload: MappingStartRequest,
    session: Session = Depends(get_session),
    controller: PipelineController = Depends(get_pipeline_controller),
) -> dict:
    try:
        result = controller.start_mapping(payload.retry_unresolved)
    except PipelineConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    run = _record_start(session, result)
    return {**result, "id": str(run.id)}


@router.post("/mapping/stop", dependencies=[Depends(require_local_action)])
def stop_mapping(
    controller: PipelineController = Depends(get_pipeline_controller),
) -> dict:
    return controller.stop_mapping()
