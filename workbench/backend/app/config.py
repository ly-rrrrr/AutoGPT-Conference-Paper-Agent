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


@lru_cache
def get_settings() -> Settings:
    return Settings()

