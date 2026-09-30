from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.dashboard import router as dashboard_router
from app.api.imports import router as imports_router
from app.api.papers import router as papers_router
from app.api.pipelines import router as pipelines_router
from app.api.preferences import router as preferences_router
from app.api.knowledge import router as knowledge_router
from app.api.runs import router as runs_router
from app.database import database_ready
from app.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="科研工作台", version="0.1.0")
    app.include_router(dashboard_router)
    app.include_router(imports_router)
    app.include_router(papers_router)
    app.include_router(pipelines_router)
    app.include_router(runs_router)
    app.include_router(preferences_router)
    app.include_router(knowledge_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        ready = database_ready()
        return {
            "status": "ok" if ready else "degraded",
            "database": "ready" if ready else "unavailable",
        }

    frontend = get_settings().frontend_dist
    assets = frontend / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_route(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API 不存在")
        index = frontend / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=503,
                detail="工作台网页尚未构建，请运行 启动科研工作台.cmd",
            )
        return FileResponse(index)

    return app


app = create_app()
