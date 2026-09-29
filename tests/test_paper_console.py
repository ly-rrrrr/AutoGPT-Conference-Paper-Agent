import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "paper_console.py"
SPEC = importlib.util.spec_from_file_location("paper_console", MODULE_PATH)
assert SPEC and SPEC.loader
console = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(console)


class PaperConsoleTest(unittest.TestCase):
    def test_discovers_documented_sibling_autogpt_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "AutoGPT-Conference-Paper-Agent"
            project.mkdir()
            platform = root / "AutoGPT" / "autogpt_platform"
            platform.mkdir(parents=True)
            (platform / "docker-compose.yml").write_text("services: {}", encoding="utf-8")

            self.assertEqual(console.discover_platform(project, None), platform.resolve())

    def test_platform_override_must_contain_compose_file(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "missing"
            invalid.mkdir()

            with self.assertRaisesRegex(ValueError, "docker-compose.yml"):
                console.discover_platform(Path(directory), str(invalid))

    def test_describes_latest_execution_in_plain_chinese(self):
        self.assertEqual(
            console.describe_runs(
                {
                    "runs": [
                        {"id": "new-run", "status": "RUNNING"},
                        {"id": "old-run", "status": "COMPLETED"},
                    ]
                }
            ),
            "最近一次论文任务：运行中（new-run）",
        )

    def test_describes_empty_execution_history(self):
        self.assertEqual(console.describe_runs({"runs": []}), "尚无论文任务记录")

    def test_skips_services_that_are_already_running(self):
        required = ["rest_server", "executor", "database_manager"]

        self.assertEqual(
            console.services_to_start(required, "rest_server\nexecutor\ndatabase_manager\n"),
            [],
        )

    def test_returns_only_services_that_are_not_running(self):
        required = ["rest_server", "executor", "database_manager"]

        self.assertEqual(
            console.services_to_start(required, "rest_server\ndatabase_manager\n"),
            ["executor"],
        )


if __name__ == "__main__":
    unittest.main()
