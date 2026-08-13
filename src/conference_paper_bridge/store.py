import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from backend.blocks.conference_paper.models import LikesResult, LikesTask
from backend.conference_paper_bridge.models import (
    BridgeRunStatus,
    ClaimedTask,
    EnqueueResponse,
    RunStateCounts,
    TaskState,
)


class TaskStoreError(Exception):
    pass


class TaskNotFoundError(TaskStoreError):
    pass


class TaskConflictError(TaskStoreError):
    pass


class TaskStateError(TaskStoreError):
    pass


class TaskStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS likes_tasks (
                    run_id TEXT NOT NULL,
                    paper_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    arxiv_url TEXT NOT NULL,
                    arxiv_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('PENDING', 'CLAIMED', 'SUCCESS', 'FAILED')
                    ),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    likes INTEGER,
                    raw_text TEXT,
                    error_code TEXT,
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    UNIQUE (run_id, paper_key)
                )
                """
            )

    def enqueue(self, run_id: str, tasks: list[LikesTask]) -> EnqueueResponse:
        inserted = 0
        existing = 0
        with self._write_transaction() as connection:
            for task in tasks:
                row = connection.execute(
                    """
                    SELECT title, arxiv_url, arxiv_id
                    FROM likes_tasks
                    WHERE run_id = ? AND paper_key = ?
                    """,
                    (run_id, task.paper_key),
                ).fetchone()
                if row is not None:
                    if (
                        row["title"],
                        row["arxiv_url"],
                        row["arxiv_id"],
                    ) != (task.title, task.arxiv_url, task.arxiv_id):
                        raise TaskConflictError(
                            f"task {task.paper_key} does not match the existing identity"
                        )
                    existing += 1
                    continue

                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO likes_tasks (
                        run_id, paper_key, title, arxiv_url, arxiv_id, state
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        task.paper_key,
                        task.title,
                        task.arxiv_url,
                        task.arxiv_id,
                        TaskState.PENDING,
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                else:
                    existing += 1
        return EnqueueResponse(inserted=inserted, existing=existing)

    def claim_next(self, run_id: str) -> ClaimedTask | None:
        with self._write_transaction() as connection:
            row = connection.execute(
                """
                SELECT sequence, paper_key, title, arxiv_url, arxiv_id, attempts
                FROM likes_tasks
                WHERE run_id = ? AND state = ?
                ORDER BY sequence
                LIMIT 1
                """,
                (run_id, TaskState.PENDING),
            ).fetchone()
            if row is None:
                return None

            attempts = row["attempts"] + 1
            connection.execute(
                """
                UPDATE likes_tasks
                SET state = ?, attempts = ?
                WHERE sequence = ? AND state = ?
                """,
                (
                    TaskState.CLAIMED,
                    attempts,
                    row["sequence"],
                    TaskState.PENDING,
                ),
            )
            return ClaimedTask(
                task=LikesTask(
                    paper_key=row["paper_key"],
                    title=row["title"],
                    arxiv_url=row["arxiv_url"],
                    arxiv_id=row["arxiv_id"],
                ),
                attempts=attempts,
            )

    def record_result(self, run_id: str, result: LikesResult) -> None:
        with self._write_transaction() as connection:
            row = connection.execute(
                """
                SELECT arxiv_id, state
                FROM likes_tasks
                WHERE run_id = ? AND paper_key = ?
                """,
                (run_id, result.paper_key),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(f"task {result.paper_key} was not found")
            if row["arxiv_id"] != result.arxiv_id:
                raise TaskConflictError(
                    f"task {result.paper_key} has a different arXiv identity"
                )
            if row["state"] == TaskState.SUCCESS:
                raise TaskConflictError(f"task {result.paper_key} already succeeded")
            if row["state"] != TaskState.CLAIMED:
                raise TaskStateError(
                    f"task {result.paper_key} is {row['state']}, not CLAIMED"
                )

            connection.execute(
                """
                UPDATE likes_tasks
                SET state = ?, likes = ?, raw_text = ?, error_code = ?
                WHERE run_id = ? AND paper_key = ?
                """,
                (
                    result.status.value,
                    result.likes,
                    result.raw_text,
                    result.error_code,
                    run_id,
                    result.paper_key,
                ),
            )

    def status(self, run_id: str) -> BridgeRunStatus:
        with self._connection() as connection:
            state_rows = connection.execute(
                """
                SELECT state, COUNT(*) AS task_count
                FROM likes_tasks
                WHERE run_id = ?
                GROUP BY state
                """,
                (run_id,),
            ).fetchall()
            counts = {state.value: 0 for state in TaskState}
            counts.update({row["state"]: row["task_count"] for row in state_rows})
            result_rows = connection.execute(
                """
                SELECT paper_key, arxiv_id, likes, raw_text, state, error_code
                FROM likes_tasks
                WHERE run_id = ? AND state IN (?, ?)
                ORDER BY sequence
                """,
                (run_id, TaskState.SUCCESS, TaskState.FAILED),
            ).fetchall()

        return BridgeRunStatus(
            counts=RunStateCounts(
                pending=counts[TaskState.PENDING],
                claimed=counts[TaskState.CLAIMED],
                success=counts[TaskState.SUCCESS],
                failed=counts[TaskState.FAILED],
            ),
            results=[
                LikesResult(
                    paper_key=row["paper_key"],
                    arxiv_id=row["arxiv_id"],
                    likes=row["likes"],
                    raw_text=row["raw_text"],
                    status=row["state"],
                    error_code=row["error_code"],
                )
                for row in result_rows
            ],
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
