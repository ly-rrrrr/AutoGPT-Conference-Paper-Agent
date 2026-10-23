from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


WORKBENCH_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = WORKBENCH_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=WORKBENCH_ROOT / ".env",
        env_prefix="WORKBENCH_",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://workbench:workbench@127.0.0.1:55432/workbench"
    )
    source_root: Path = REPOSITORY_ROOT / "data"
    frontend_dist: Path = WORKBENCH_ROOT / "frontend" / "dist"
    asset_root: Path = WORKBENCH_ROOT / "data"
    grobid_url: str = "http://127.0.0.1:8070"
    grobid_timeout_seconds: float = 180
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str | None = None
    milvus_database: str = "default"
    milvus_collection_prefix: str = "research_workbench"
    milvus_timeout_seconds: float = 2
    outbound_proxy_url: str | None = None
    max_pdf_bytes: int = 80 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()

