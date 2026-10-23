from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

from app.config import Settings, get_settings


class MilvusClientLike(Protocol):
    def list_collections(self, **kwargs) -> list[str]: ...

    def close(self) -> None: ...


ClientFactory = Callable[..., MilvusClientLike]


def _default_client_factory(**kwargs) -> MilvusClientLike:
    from pymilvus import MilvusClient

    return MilvusClient(**kwargs)


def collection_name(asset_type: str, embedding_model: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    normalized = re.sub(r"[^a-z0-9_]+", "_", f"{asset_type}_{embedding_model}".casefold())
    normalized = normalized.strip("_")
    if not normalized:
        raise ValueError("Milvus collection 名称不能为空")
    return f"{settings.milvus_collection_prefix}_{normalized}"[:255]


def milvus_ready(
    settings: Settings | None = None,
    client_factory: ClientFactory = _default_client_factory,
) -> bool:
    settings = settings or get_settings()
    kwargs = {
        "uri": settings.milvus_uri,
        "db_name": settings.milvus_database,
        "timeout": settings.milvus_timeout_seconds,
    }
    if settings.milvus_token:
        kwargs["token"] = settings.milvus_token
    client = None
    try:
        client = client_factory(**kwargs)
        client.list_collections(timeout=settings.milvus_timeout_seconds)
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
