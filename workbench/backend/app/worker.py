import argparse
import os
import time
from pathlib import Path
from uuid import UUID

from app.database import session_scope
from app.config import get_settings
from app.job_queue import claim_next_run, fail_run, finish_run, worker_identity
from app.lineage_extractor import extract_lineage
from app.models import Paper, PipelineRun


def parent_is_alive(parent_pid: int | None) -> bool:
    if parent_pid is None:
        return True
    try:
        os.kill(parent_pid, 0)
        return True
    except OSError:
        return False


def execute_claimed_run(run_id: UUID) -> None:
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            return
        if run.pipeline == "lineage":
            paper = session.get(Paper, UUID(run.config["paper_id"]))
            if paper is None:
                raise RuntimeError("论文不存在")
            run.counters = extract_lineage(session, paper)
            return
        raise RuntimeError(f"Worker 不支持任务类型：{run.pipeline}")


def run_worker(parent_pid: int | None = None, poll_seconds: float = 1.0) -> None:
    owner = worker_identity()
    while parent_is_alive(parent_pid):
        with session_scope() as session:
            run = claim_next_run(session, owner)
            run_id = run.id if run else None
        if run_id is None:
            time.sleep(poll_seconds)
            continue
        try:
            execute_claimed_run(run_id)
            with session_scope() as session:
                finish_run(session, run_id)
        except Exception as error:
            with session_scope() as session:
                fail_run(session, run_id, error)


def _process_is_alive(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False


def _claim_pid_file() -> Path | None:
    runtime_root = get_settings().asset_root / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    pid_path = runtime_root / "worker.pid"
    if pid_path.is_file():
        try:
            existing = int(pid_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            existing = 0
        if existing and existing != os.getpid() and _process_is_alive(existing):
            return None
        pid_path.unlink(missing_ok=True)
    try:
        descriptor = os.open(pid_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    with os.fdopen(descriptor, "w", encoding="ascii") as target:
        target.write(str(os.getpid()))
    return pid_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    arguments = parser.parse_args()
    pid_path = _claim_pid_file()
    if pid_path is None:
        return
    try:
        run_worker(arguments.parent_pid, arguments.poll_seconds)
    finally:
        try:
            if pid_path.read_text(encoding="ascii").strip() == str(os.getpid()):
                pid_path.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    main()
