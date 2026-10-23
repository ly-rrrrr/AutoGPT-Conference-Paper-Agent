import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.config import WORKBENCH_ROOT, get_settings


STORAGE_CONFIG_PATH = WORKBENCH_ROOT / "data" / "system" / "storage.json"
RECOMMENDED_FREE_BYTES = 100 * 1024**3


def _saved_root() -> Path | None:
    try:
        payload = json.loads(STORAGE_CONFIG_PATH.read_text(encoding="utf-8"))
        value = payload.get("asset_root")
        return Path(value) if isinstance(value, str) and value.strip() else None
    except (OSError, ValueError, TypeError):
        return None


def get_asset_root() -> Path:
    return (_saved_root() or get_settings().asset_root).expanduser().resolve()


def _disk_usage(path: Path) -> tuple[int, int, int]:
    existing = path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    return shutil.disk_usage(existing)


def storage_overview() -> dict:
    root = get_asset_root()
    total, used, free = _disk_usage(root)
    return {
        "asset_root": str(root),
        "source": "saved" if _saved_root() else "environment_or_default",
        "exists": root.is_dir(),
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "recommended_free_bytes": RECOMMENDED_FREE_BYTES,
        "capacity_status": "READY" if free >= RECOMMENDED_FREE_BYTES else "LOW",
        "config_path": str(STORAGE_CONFIG_PATH),
    }


def save_asset_root(value: str) -> dict:
    candidate = Path(value.strip()).expanduser()
    if not candidate.is_absolute():
        raise ValueError("存储目录必须是绝对路径，例如 E:\\ResearchAtlas")
    root = candidate.resolve()
    if root == Path(root.anchor):
        raise ValueError("不能直接使用磁盘根目录，请选择一个专用子目录")
    if root.exists() and not root.is_dir():
        raise ValueError("指定路径已存在，但不是文件夹")
    root.mkdir(parents=True, exist_ok=True)
    probe = root / f".workbench-write-test-{uuid.uuid4().hex}"
    try:
        probe.write_text("ok", encoding="ascii")
    finally:
        probe.unlink(missing_ok=True)

    STORAGE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STORAGE_CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "asset_root": str(root),
                "updated_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, STORAGE_CONFIG_PATH)
    return storage_overview()
