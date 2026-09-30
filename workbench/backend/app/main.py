from fastapi import FastAPI

from app.database import database_ready


def create_app() -> FastAPI:
    app = FastAPI(title="科研工作台", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        ready = database_ready()
        return {
            "status": "ok" if ready else "degraded",
            "database": "ready" if ready else "unavailable",
        }

    return app


app = create_app()

