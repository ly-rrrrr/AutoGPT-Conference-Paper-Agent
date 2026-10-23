from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

from app.config import Settings, get_settings


class MilvusClientLike(Protocol):
    def list_collections(self, **kwargs) -> list[str]: ...

    def has_collection(self, collection_name: str, **kwargs) -> bool: ...

    def create_collection(self, collection_name: str, **kwargs) -> None: ...

    def upsert(self, collection_name: str, data: list[dict], **kwargs) -> dict: ...

    def search(self, collection_name: str, **kwargs) -> list[list[dict]]: ...

    def close(self) -> None: ...


ClientFactory = Callable[..., MilvusClientLike]


def _default_client_factory(**kwargs) -> MilvusClientLike:
    from pymilvus import MilvusClient

    return MilvusClient(**kwargs)


def collection_name(
    asset_type: str,
    embedding_model: str,
    settings: Settings | None = None,
    dimension: int | None = None,
) -> str:
    settings = settings or get_settings()
    identity = f"{asset_type}_{embedding_model}"
    if dimension is not None:
        identity = f"{identity}_d{dimension}"
    normalized = re.sub(r"[^a-z0-9_]+", "_", identity.casefold())
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


class VectorStore:
    def __init__(
        self,
        settings: Settings | None = None,
        client_factory: ClientFactory = _default_client_factory,
    ):
        self.settings = settings or get_settings()
        kwargs = {
            "uri": self.settings.milvus_uri,
            "db_name": self.settings.milvus_database,
            "timeout": self.settings.milvus_timeout_seconds,
        }
        if self.settings.milvus_token:
            kwargs["token"] = self.settings.milvus_token
        self.client = client_factory(**kwargs)

    def close(self) -> None:
        self.client.close()

    def ensure_collection(
        self, asset_type: str, embedding_model: str, dimension: int
    ) -> str:
        if dimension <= 0:
            raise ValueError("embedding dimension 必须大于 0")
        name = collection_name(asset_type, embedding_model, self.settings, dimension)
        if not self.client.has_collection(name, timeout=self.settings.milvus_timeout_seconds):
            self.client.create_collection(
                collection_name=name,
                dimension=dimension,
                primary_field_name="id",
                id_type="string",
                vector_field_name="vector",
                metric_type="COSINE",
                auto_id=False,
                max_length=80,
                enable_dynamic_field=True,
                timeout=self.settings.milvus_timeout_seconds,
            )
        return name

    def upsert(
        self,
        collection: str,
        *,
        entity_id: str,
        vector: list[float],
        paper_id: str,
        chunk_id: str,
        content_sha256: str,
        kind: str,
    ) -> dict:
        return self.client.upsert(
            collection,
            data=[
                {
                    "id": entity_id,
                    "vector": vector,
                    "paper_id": paper_id,
                    "chunk_id": chunk_id,
                    "content_sha256": content_sha256,
                    "kind": kind,
                }
            ],
            timeout=self.settings.milvus_timeout_seconds,
        )

    def upsert_many(self, collection: str, items: list[dict]) -> dict:
        return self.client.upsert(
            collection,
            data=items,
            timeout=self.settings.milvus_timeout_seconds,
        )

    def search(
        self,
        collection: str,
        vector: list[float],
        *,
        limit: int = 20,
        filter_expression: str = "",
    ) -> list[dict]:
        results = self.client.search(
            collection,
            data=[vector],
            filter=filter_expression,
            limit=limit,
            output_fields=["paper_id", "chunk_id", "content_sha256", "kind"],
            search_params={"metric_type": "COSINE"},
            timeout=self.settings.milvus_timeout_seconds,
        )
        return results[0] if results else []
