import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


WORKBENCH_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = WORKBENCH_ROOT.parent
BACKEND_ROOT = WORKBENCH_ROOT / "backend"
FRONTEND_ROOT = WORKBENCH_ROOT / "frontend"
COMPOSE_FILE = WORKBENCH_ROOT / "docker-compose.yml"
VENV_ROOT = WORKBENCH_ROOT / ".venv"
VENV_PYTHON = VENV_ROOT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
URL = "http://127.0.0.1:8767"


def startup_actions(probe) -> list[str]:
    actions = []
    if not probe.database_running():
        actions.append("compose_up_db")
    if not probe.frontend_ready():
        actions.append("frontend_build")
    return [*actions, "migrate", "sync", "serve"]


def run(command: list[str], cwd: Path | None = None, env: dict | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "命令执行失败")[-3000:])
    return result.stdout


class LocalProbe:
    def database_running(self) -> bool:
        try:
            output = run(
                ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--status", "running", "--services"],
                WORKBENCH_ROOT,
            )
            return "db" in output.split()
        except (OSError, RuntimeError):
            return False

    def frontend_ready(self) -> bool:
        dist = FRONTEND_ROOT / "dist"
        return (dist / "index.html").is_file() and (dist / "assets").is_dir()


def workbench_is_running() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/health", timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def ensure_backend() -> None:
    if sys.version_info < (3, 12):
        raise RuntimeError("科研工作台需要 Python 3.12 或更高版本")
    if not VENV_PYTHON.is_file():
        print("[准备] 创建工作台 Python 环境…", flush=True)
        run([sys.executable, "-m", "venv", str(VENV_ROOT)])
    check = subprocess.run(
        [str(VENV_PYTHON), "-c", "import fastapi, sqlalchemy, uvicorn, alembic, psycopg"],
        capture_output=True,
    )
    if check.returncode:
        print("[准备] 安装工作台后端依赖…", flush=True)
        run([str(VENV_PYTHON), "-m", "pip", "install", "-e", str(BACKEND_ROOT)])


def ensure_docker() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("未找到 Docker。请先安装 Docker Desktop。")
    try:
        run(["docker", "info"])
        return
    except RuntimeError:
        desktop = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"
        if not desktop.is_file():
            raise RuntimeError("Docker Desktop 尚未运行，请手动打开后重试")
        print("[准备] 正在启动 Docker Desktop…", flush=True)
        subprocess.Popen([str(desktop)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            run(["docker", "info"])
            return
        except RuntimeError:
            continue
    raise RuntimeError("Docker Desktop 在两分钟内未就绪，请查看 Docker 窗口中的提示")


def ensure_frontend() -> None:
    pnpm = shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if shutil.which("node") is None or pnpm is None:
        raise RuntimeError("首次构建前端需要 Node.js 与 pnpm；安装后重新双击启动脚本")
    print("[准备] 构建工作台网页（仅首次或前端产物缺失时）…", flush=True)
    if not (FRONTEND_ROOT / "node_modules").is_dir():
        run([pnpm, "install", "--frozen-lockfile"], FRONTEND_ROOT)
    run([pnpm, "build"], FRONTEND_ROOT)


def source_root() -> Path:
    override = os.environ.get("WORKBENCH_SOURCE_ROOT")
    if override:
        return Path(override).resolve()
    sibling = REPOSITORY_ROOT.parent / "conference-paper-agent" / "projects" / "conference-paper-research-agent" / "data"
    if (sibling / "runs").is_dir():
        return sibling.resolve()
    return (REPOSITORY_ROOT / "data").resolve()


def runtime_env() -> dict[str, str]:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "WORKBENCH_SOURCE_ROOT": str(source_root())}


def wait_for_database() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "db", "pg_isready", "-U", "workbench"],
            cwd=WORKBENCH_ROOT,
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("工作台数据库未能在一分钟内就绪")


def sync_assets(env: dict[str, str]) -> None:
    script = (
        "from dataclasses import asdict; "
        "from app.config import get_settings; "
        "from app.database import session_scope; "
        "from app.importers import AssetImporter; "
        "ctx=session_scope(); session=ctx.__enter__(); "
        "summary=AssetImporter(session,get_settings().source_root).sync(); "
        "ctx.__exit__(None,None,None); print('同步完成：'+str(asdict(summary)))"
    )
    output = run([str(VENV_PYTHON), "-c", script], BACKEND_ROOT, env)
    print(output.strip(), flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("科研工作台启动器 · http://127.0.0.1:8767", flush=True)
    if workbench_is_running():
        print("工作台已经运行，正在打开浏览器。", flush=True)
        webbrowser.open(URL)
        return 0
    ensure_backend()
    ensure_docker()
    probe = LocalProbe()
    actions = startup_actions(probe)
    env = runtime_env()
    if "compose_up_db" in actions:
        print("[1/4] 启动 PostgreSQL…", flush=True)
        run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "db"], WORKBENCH_ROOT)
    wait_for_database()
    if "frontend_build" in actions:
        ensure_frontend()
    print("[2/4] 更新工作台数据结构…", flush=True)
    run([str(VENV_PYTHON), "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], BACKEND_ROOT, env)
    print(f"[3/4] 同步已有论文资产：{source_root()}", flush=True)
    sync_assets(env)
    print("[4/4] 工作台已就绪。保留此窗口即可持续使用；关闭窗口会停止网页服务。", flush=True)
    threading.Timer(1.2, lambda: webbrowser.open(URL)).start()
    return subprocess.call(
        [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8767"],
        cwd=BACKEND_ROOT,
        env=env,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n工作台网页服务已停止；数据库与论文数据仍保留。")
        raise SystemExit(0)
    except Exception as error:
        print(f"\n启动未完成：{error}", file=sys.stderr)
        raise SystemExit(1)
