import os
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPOSITORY_ROOT / "启动科研工作台.cmd"


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd regression")
def test_windows_launcher_passes_start_script_to_python(tmp_path):
    fake_python = tmp_path / "python.cmd"
    fake_python.write_bytes(
        b"@echo PYTHON_ARGS=%*\r\n@echo PYTHON_UTF8=[%PYTHONUTF8%]\r\n@exit /b 0\r\n"
    )
    environment = {
        **os.environ,
        "PATH": os.pathsep.join(
            [str(tmp_path), str(Path(os.environ["SystemRoot"]) / "System32")]
        ),
        "PYTHONUTF8": "1",
    }

    result = subprocess.run(
        [
            os.environ.get("ComSpec", "cmd.exe"),
            "/d",
            "/c",
            str(LAUNCHER),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert result.returncode == 0
    assert "PYTHON_ARGS=" in result.stdout
    assert "workbench\\scripts\\start.py" in result.stdout
    assert "PYTHON_UTF8=[1]" in result.stdout
    assert "is not recognized" not in result.stdout
