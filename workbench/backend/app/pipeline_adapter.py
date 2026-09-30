import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol


ACTIVE_STATES = {"QUEUED", "RUNNING"}
STATE_MAP = {
    "QUEUED": "QUEUED",
    "RUNNING": "RUNNING",
    "COMPLETED": "COMPLETED",
    "FAILED": "FAILED",
    "TERMINATED": "STOPPED",
    "STOPPED": "STOPPED",
}


class PipelineConflictError(RuntimeError):
    pass


class PipelineBackendError(RuntimeError):
    pass


class AnalysisBackend(Protocol):
    def request(self, action: str, config: dict | None = None) -> dict: ...


@dataclass(frozen=True)
class AnalysisStart:
    run_id: str
    analysis_concurrency: int
    analysis_request_interval_seconds: int
    max_new_analyses_per_run: int


def discover_platform(repository_root: Path, override: Path | None = None) -> Path:
    candidates = (
        [override]
        if override
        else [
            repository_root / "autogpt_platform",
            repository_root.parent / "AutoGPT" / "autogpt_platform",
            repository_root.parent / "conference-paper-agent" / "autogpt_platform",
        ]
    )
    for candidate in candidates:
        if candidate and (candidate / "docker-compose.yml").is_file():
            return candidate.resolve()
    raise PipelineBackendError("找不到 AutoGPT docker-compose.yml，请设置 WORKBENCH_PLATFORM_ROOT")


class DockerAnalysisBackend:
    def __init__(self, platform_root: Path, backend_script: Path):
        self.platform_root = platform_root
        self.backend_script = backend_script

    def request(self, action: str, config: dict | None = None) -> dict:
        request = json.dumps(
            {
                "action": action,
                "user_id": os.environ.get("PAPER_USER_ID"),
                "graph_id": os.environ.get("PAPER_GRAPH_ID"),
                "config": config,
            },
            ensure_ascii=True,
        )
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "rest_server", "python", "-", request],
            cwd=self.platform_root,
            input=self.backend_script.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if result.returncode:
            raise PipelineBackendError((result.stderr or result.stdout)[-2000:])
        for line in result.stdout.splitlines():
            if line.startswith("CONSOLE_RESULT="):
                return json.loads(line.split("=", 1)[1])
        raise PipelineBackendError("未收到 AutoGPT 后台响应")


class PipelineController:
    def __init__(
        self,
        repository_root: Path,
        platform_root: Path,
        data_root: Path,
        backend: AnalysisBackend,
    ):
        self.repository_root = repository_root
        self.platform_root = platform_root
        self.data_root = data_root
        self.backend = backend
        self._mapping_process: subprocess.Popen | None = None
        self._lock = Lock()

    def status(self) -> dict:
        analysis_error = None
        try:
            result = self.backend.request("status")
        except (OSError, RuntimeError, subprocess.SubprocessError):
            result = {"runs": []}
            analysis_error = "AutoGPT 服务未连接"
        runs = [
            {**run, "status": STATE_MAP.get(str(run.get("status")), "FAILED")}
            for run in result.get("runs", [])
        ]
        mapping_running = bool(
            self._mapping_process and self._mapping_process.poll() is None
        )
        return {
            "analysis_runs": runs,
            "analysis_error": analysis_error,
            "mapping": {
                "status": "RUNNING" if mapping_running else "IDLE",
                "exit_code": (
                    self._mapping_process.poll() if self._mapping_process else None
                ),
            },
        }

    def start_analysis(self, request: AnalysisStart) -> dict:
        with self._lock:
            active = [
                run
                for run in self.backend.request("status").get("runs", [])
                if str(run.get("status")) in ACTIVE_STATES
            ]
            if active:
                raise PipelineConflictError("已有分析任务正在运行或排队")
            result = self.backend.request("start", asdict(request))
            return {
                "external_id": result["execution_id"],
                "run_key": request.run_id,
                "pipeline": "analysis",
                "status": "QUEUED",
                "message": result.get("message", "任务已提交"),
                "config": asdict(request),
            }

    def stop_analysis(self) -> dict:
        with self._lock:
            result = self.backend.request("stop")
            return {"status": "STOPPED", "message": result.get("message", "已停止")}

    def start_mapping(self, retry_unresolved: bool = False) -> dict:
        with self._lock:
            if self._mapping_process and self._mapping_process.poll() is None:
                raise PipelineConflictError("映射任务已在运行")
            output = self.data_root / "eccv-2026-mapping"
            output.mkdir(parents=True, exist_ok=True)
            command = [
                sys.executable,
                "-u",
                str(self.repository_root / "scripts" / "map_eccv_arxiv.py"),
                "--output",
                str(output),
                "--limit",
                "0",
            ]
            if retry_unresolved:
                command.append("--retry-unresolved")
            log = (self.data_root / "workbench-mapping.log").open(
                "a", encoding="utf-8"
            )
            self._mapping_process = subprocess.Popen(
                command,
                stdout=log,
                stderr=log,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log.close()
            return {
                "external_id": str(self._mapping_process.pid),
                "run_key": "eccv-2026-mapping",
                "pipeline": "mapping",
                "status": "RUNNING",
                "message": "映射已启动，进度会保存到断点文件",
                "config": {"retry_unresolved": retry_unresolved},
            }

    def stop_mapping(self) -> dict:
        with self._lock:
            if self._mapping_process and self._mapping_process.poll() is None:
                self._mapping_process.terminate()
            return {"status": "STOPPED", "message": "映射停止请求已发送"}
