from dataclasses import asdict
from threading import Lock

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.database import session_scope
from app.importers import AssetImporter


router = APIRouter(prefix="/api/imports", tags=["imports"])
sync_lock = Lock()


def execute_sync() -> dict[str, int]:
    with session_scope() as session:
        summary = AssetImporter(session, get_settings().source_root).sync()
    return asdict(summary)


@router.post("/sync")
def sync_assets() -> dict[str, int]:
    if not sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="数据同步正在运行")
    try:
        return execute_sync()
    finally:
        sync_lock.release()
