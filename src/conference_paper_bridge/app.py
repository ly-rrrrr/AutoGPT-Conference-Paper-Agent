import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.blocks.conference_paper.models import LikesResult
from backend.conference_paper_bridge.models import (
    BridgeRunStatus,
    ClaimResponse,
    EnqueueRequest,
    EnqueueResponse,
    ResultResponse,
)
from backend.conference_paper_bridge.store import (
    TaskConflictError,
    TaskNotFoundError,
    TaskStateError,
    TaskStore,
)


def create_app(
    db_path: Path | str | None = None,
    token: str | None = None,
) -> FastAPI:
    database = db_path or os.getenv(
        "CONFERENCE_PAPER_BRIDGE_DB", "conference-paper-bridge.db"
    )
    expected_token = (
        token if token is not None else os.getenv("CONFERENCE_PAPER_BRIDGE_TOKEN")
    )
    if not expected_token:
        raise ValueError("CONFERENCE_PAPER_BRIDGE_TOKEN is required")

    store = TaskStore(database)
    store.initialize()
    bearer = HTTPBearer(auto_error=False)
    app = FastAPI(title="Conference Paper RPA Bridge")

    def authorize(
        credentials: HTTPAuthorizationCredentials | None = Security(bearer),
    ) -> None:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not secrets.compare_digest(credentials.credentials, expected_token)
        ):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.exception_handler(TaskNotFoundError)
    async def task_not_found(_, error: TaskNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(TaskConflictError)
    @app.exception_handler(TaskStateError)
    async def task_conflict(
        _, error: TaskConflictError | TaskStateError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.post("/runs/{run_id}/tasks", status_code=201)
    def enqueue_tasks(
        run_id: str,
        request: EnqueueRequest,
        _: None = Security(authorize),
    ) -> EnqueueResponse:
        return store.enqueue(run_id, request.tasks)

    @app.get("/runs/{run_id}/tasks/next")
    def next_task(
        run_id: str,
        _: None = Security(authorize),
    ) -> ClaimResponse:
        claimed = store.claim_next(run_id)
        if claimed is None:
            return ClaimResponse()
        return ClaimResponse(task=claimed.task, attempts=claimed.attempts)

    @app.post("/runs/{run_id}/results", status_code=201)
    def save_result(
        run_id: str,
        result: LikesResult,
        _: None = Security(authorize),
    ) -> ResultResponse:
        store.record_result(run_id, result)
        return ResultResponse(accepted=True)

    @app.get("/runs/{run_id}/status")
    def run_status(
        run_id: str,
        _: None = Security(authorize),
    ) -> BridgeRunStatus:
        return store.status(run_id)

    return app
