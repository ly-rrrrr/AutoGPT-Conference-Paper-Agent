import importlib.util
from pathlib import Path


START_PATH = Path(__file__).parents[2] / "scripts" / "start.py"


def load_startup():
    spec = importlib.util.spec_from_file_location("workbench_start", START_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProbe:
    def __init__(self, database_running: bool, frontend_ready: bool = True):
        self._database_running = database_running
        self._frontend_ready = frontend_ready

    def database_running(self) -> bool:
        return self._database_running

    def frontend_ready(self) -> bool:
        return self._frontend_ready


def test_startup_reuses_healthy_database():
    startup = load_startup()

    actions = startup.startup_actions(FakeProbe(database_running=True))

    assert "compose_up_db" not in actions
    assert actions == ["migrate", "sync", "serve"]


def test_startup_builds_missing_frontend_before_migration():
    startup = load_startup()

    actions = startup.startup_actions(
        FakeProbe(database_running=False, frontend_ready=False)
    )

    assert actions == [
        "compose_up_db",
        "frontend_build",
        "migrate",
        "sync",
        "serve",
    ]
