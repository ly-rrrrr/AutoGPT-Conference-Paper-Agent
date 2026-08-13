from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


BASELINE = "6dcf0e22f84ce49c289adec4504a3d4ec186bb3a"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def require_autogpt_root(root: Path) -> None:
    required = [
        root / "autogpt_platform" / "docker-compose.yml",
        root / "autogpt_platform" / "backend" / "backend" / "blocks",
        root / "autogpt_platform" / "frontend",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            "目标目录不是兼容的 AutoGPT 仓库，缺少：\n- " + "\n- ".join(missing)
        )


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, dirs_exist_ok=True)


def apply_platform_patch(project_root: Path, autogpt_root: Path) -> None:
    patch = project_root / "patches" / "autogpt-platform.patch"
    check = run_git(autogpt_root, "apply", "--check", str(patch))
    if check.returncode == 0:
        applied = run_git(autogpt_root, "apply", str(patch))
        if applied.returncode != 0:
            raise SystemExit(applied.stderr.strip() or "AutoGPT 适配补丁应用失败")
        return

    reverse_check = run_git(autogpt_root, "apply", "--reverse", "--check", str(patch))
    if reverse_check.returncode == 0:
        print("AutoGPT 适配补丁已经应用，跳过。")
        return

    current = run_git(autogpt_root, "rev-parse", "HEAD")
    current_revision = current.stdout.strip() if current.returncode == 0 else "未知"
    raise SystemExit(
        "AutoGPT 适配补丁与当前代码不兼容。\n"
        f"当前版本：{current_revision}\n"
        f"推荐版本：{BASELINE}\n"
        f"请在 AutoGPT 仓库执行：git checkout {BASELINE}"
    )


def install(project_root: Path, autogpt_root: Path) -> None:
    require_autogpt_root(autogpt_root)
    apply_platform_patch(project_root, autogpt_root)

    backend = autogpt_root / "autogpt_platform" / "backend"
    copy_tree(
        project_root / "src" / "conference_paper",
        backend / "backend" / "blocks" / "conference_paper",
    )
    copy_tree(
        project_root / "src" / "conference_paper_bridge",
        backend / "backend" / "conference_paper_bridge",
    )
    shutil.copy2(
        project_root / "src" / "json_blocks.py",
        backend / "backend" / "blocks" / "json_blocks.py",
    )
    shutil.copy2(
        project_root / "src" / "test_json_blocks.py",
        backend / "backend" / "blocks" / "test" / "test_json_blocks.py",
    )
    shutil.copy2(
        project_root / "agent" / "conference-paper-research-agent.json",
        backend / "agents" / "conference-paper-research-agent.json",
    )

    project_target = autogpt_root / "projects" / "conference-paper-research-agent"
    copy_tree(project_root / "docs", project_target / "docs")
    copy_tree(project_root / "shadowbot", project_target / "shadowbot")
    copy_tree(project_root / "fixtures", project_target / "fixtures")
    (project_target / "data" / "runs").mkdir(parents=True, exist_ok=True)

    print("安装完成。下一步：")
    print(f"1. cd {autogpt_root / 'autogpt_platform'}")
    print("2. docker compose up -d --build")
    print("3. 打开 http://localhost:3000")
    print(
        "4. 导入 autogpt_platform/backend/agents/"
        "conference-paper-research-agent.json"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="安装顶会论文研究 Agent 到 AutoGPT")
    parser.add_argument(
        "--autogpt-root",
        required=True,
        type=Path,
        help="AutoGPT 仓库根目录",
    )
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    install(project_root, args.autogpt_root.resolve())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
