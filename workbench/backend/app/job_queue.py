import socket
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import PipelineEvent, PipelineRun


WORKER_PIPELINES = ("lineage", "vector_index")


def worker_identity() -> str:
    return f"{socket.gethostname()}:{__import__('os').getpid()}"


def enqueue_run(
    session: Session,
    *,
    run_key: str,
    pipeline: str,
    config: dict,
    max_attempts: int = 2,
) -> PipelineRun:
    active = session.scalar(
        select(PipelineRun).where(
            PipelineRun.run_key == run_key,
            PipelineRun.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    if active is not None:
        return active
    now = datetime.now(UTC)
    run = PipelineRun(
        run_key=run_key,
        pipeline=pipeline,
        status="QUEUED",
        config=config,
        counters={},
        available_at=now,
        max_attempts=max_attempts,
    )
    session.add(run)
    session.flush()
    session.add(
        PipelineEvent(
            pipeline_run_id=run.id,
            level="INFO",
            event_type="JOB_QUEUED",
            message="任务已进入持久化队列",
            details={"pipeline": pipeline},
        )
    )
    return run


def claim_next_run(
    session: Session,
    owner: str,
    *,
    lease_seconds: int = 300,
) -> PipelineRun | None:
    now = datetime.now(UTC)
    due = or_(PipelineRun.available_at.is_(None), PipelineRun.available_at <= now)
    claimable = or_(
        and_(PipelineRun.status == "QUEUED", due),
        and_(
            PipelineRun.status == "RUNNING",
            PipelineRun.lease_expires_at.is_not(None),
            PipelineRun.lease_expires_at < now,
        ),
    )
    run = session.scalar(
        select(PipelineRun)
        .where(PipelineRun.pipeline.in_(WORKER_PIPELINES), claimable)
        .order_by(PipelineRun.available_at.asc().nullsfirst(), PipelineRun.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if run is None:
        return None
    reclaimed = run.status == "RUNNING"
    run.status = "RUNNING"
    run.started_at = run.started_at or now
    run.lease_owner = owner
    run.lease_expires_at = now + timedelta(seconds=lease_seconds)
    run.heartbeat_at = now
    run.attempt_count += 1
    session.add(
        PipelineEvent(
            pipeline_run_id=run.id,
            level="WARNING" if reclaimed else "INFO",
            event_type="JOB_RECLAIMED" if reclaimed else "JOB_STARTED",
            message="超时任务已被重新接管" if reclaimed else "Worker 已开始执行任务",
            details={"worker": owner, "attempt": run.attempt_count},
        )
    )
    session.flush()
    return run


def finish_run(session: Session, run_id: UUID) -> None:
    run = session.get(PipelineRun, run_id)
    if run is None:
        return
    now = datetime.now(UTC)
    run.status = "SUCCESS"
    run.ended_at = now
    run.lease_owner = None
    run.lease_expires_at = None
    run.heartbeat_at = now
    session.add(
        PipelineEvent(
            pipeline_run_id=run.id,
            level="INFO",
            event_type="JOB_SUCCEEDED",
            message="任务执行完成",
            details={"attempt": run.attempt_count},
        )
    )


def fail_run(session: Session, run_id: UUID, error: Exception) -> None:
    run = session.get(PipelineRun, run_id)
    if run is None:
        return
    now = datetime.now(UTC)
    run.last_error = str(error)
    run.lease_owner = None
    run.lease_expires_at = None
    run.heartbeat_at = now
    retrying = run.attempt_count < run.max_attempts
    run.status = "QUEUED" if retrying else "FAILED"
    run.available_at = now + timedelta(seconds=15) if retrying else None
    run.ended_at = None if retrying else now
    session.add(
        PipelineEvent(
            pipeline_run_id=run.id,
            level="WARNING" if retrying else "ERROR",
            event_type="JOB_RETRY_SCHEDULED" if retrying else "JOB_FAILED",
            message="任务将在短暂等待后重试" if retrying else "任务执行失败",
            details={"attempt": run.attempt_count, "error": str(error)},
        )
    )
