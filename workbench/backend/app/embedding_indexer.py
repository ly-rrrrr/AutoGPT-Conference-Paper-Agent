from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DocumentChunk,
    DocumentAsset,
    DocumentAssetRevision,
    EmbeddingProviderConfig,
    VectorIndexRecord,
)
from app.secret_store import get_secret
from app.vector_store import VectorStore, collection_name


INDEX_VERSION = "document-chunk-v1"


class EmbeddingIndexError(RuntimeError):
    pass


def request_embeddings(
    config: EmbeddingProviderConfig,
    api_key: str,
    texts: list[str],
    *,
    timeout_seconds: float = 120,
) -> list[list[float]]:
    try:
        response = httpx.post(
            f"{config.base_url.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": config.model_name,
                "input": texts,
                "encoding_format": "float",
                "dimensions": config.dimension,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        rows = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in rows]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise EmbeddingIndexError(f"Embedding 请求失败：{error}") from error
    if len(vectors) != len(texts):
        raise EmbeddingIndexError(
            f"Embedding 返回数量不一致：请求 {len(texts)}，返回 {len(vectors)}"
        )
    if any(len(vector) != config.dimension for vector in vectors):
        dimensions = sorted({len(vector) for vector in vectors})
        raise EmbeddingIndexError(
            f"Embedding 维度与配置不一致：配置 {config.dimension}，返回 {dimensions}"
        )
    return vectors


def pending_chunks(
    session: Session,
    config: EmbeddingProviderConfig,
    *,
    limit: int,
) -> list[DocumentChunk]:
    existing = (
        select(VectorIndexRecord.id)
        .where(
            VectorIndexRecord.document_chunk_id == DocumentChunk.id,
            VectorIndexRecord.embedding_model == config.model_name,
            VectorIndexRecord.embedding_dimension == config.dimension,
            VectorIndexRecord.index_version == INDEX_VERSION,
            VectorIndexRecord.content_sha256 == DocumentChunk.content_sha256,
            VectorIndexRecord.status == "INDEXED",
        )
        .correlate(DocumentChunk)
        .exists()
    )
    return list(
        session.scalars(
            select(DocumentChunk)
            .join(
                DocumentAssetRevision,
                DocumentAssetRevision.id == DocumentChunk.asset_revision_id,
            )
            .join(
                DocumentAsset,
                DocumentAsset.id == DocumentAssetRevision.document_asset_id,
            )
            .where(
                DocumentAsset.sha256 == DocumentAssetRevision.content_sha256,
                ~existing,
            )
            .order_by(DocumentChunk.paper_id, DocumentChunk.ordinal)
            .limit(limit)
        )
    )


def index_document_chunks(
    session: Session,
    config_id: UUID,
    *,
    max_chunks: int = 500,
    batch_size: int = 32,
    vector_store_factory=VectorStore,
) -> dict:
    config = session.get(EmbeddingProviderConfig, config_id)
    if config is None or config.status != "ACTIVE":
        raise EmbeddingIndexError("Embedding 配置不存在或未启用")
    api_key = get_secret(config.secret_ref)
    if not api_key:
        raise EmbeddingIndexError("Embedding 配置尚未保存 API Key")
    chunks = pending_chunks(session, config, limit=max_chunks)
    if not chunks:
        return {"selected": 0, "indexed": 0, "model": config.model_name}
    store = vector_store_factory()
    indexed = 0
    try:
        collection = store.ensure_collection(
            "document_chunk", config.model_name, config.dimension
        )
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = request_embeddings(config, api_key, [chunk.text for chunk in batch])
            store.upsert_many(
                collection,
                [
                    {
                        "id": str(chunk.id),
                        "vector": vector,
                        "paper_id": str(chunk.paper_id),
                        "chunk_id": str(chunk.id),
                        "content_sha256": chunk.content_sha256,
                        "kind": chunk.kind,
                    }
                    for chunk, vector in zip(batch, vectors, strict=True)
                ],
            )
            for chunk in batch:
                record = session.scalar(
                    select(VectorIndexRecord).where(
                        VectorIndexRecord.document_chunk_id == chunk.id,
                        VectorIndexRecord.embedding_model == config.model_name,
                        VectorIndexRecord.embedding_dimension == config.dimension,
                        VectorIndexRecord.index_version == INDEX_VERSION,
                    )
                )
                if record is None:
                    record = VectorIndexRecord(
                        document_chunk_id=chunk.id,
                        collection_name=collection,
                        entity_id=str(chunk.id),
                        embedding_model=config.model_name,
                        embedding_dimension=config.dimension,
                        index_version=INDEX_VERSION,
                        content_sha256=chunk.content_sha256,
                        status="INDEXED",
                        indexed_at=datetime.now(UTC),
                    )
                    session.add(record)
                else:
                    record.collection_name = collection
                    record.entity_id = str(chunk.id)
                    record.embedding_dimension = config.dimension
                    record.content_sha256 = chunk.content_sha256
                    record.status = "INDEXED"
                    record.indexed_at = datetime.now(UTC)
                    record.last_error = None
            session.commit()
            indexed += len(batch)
    finally:
        store.close()
    return {
        "selected": len(chunks),
        "indexed": indexed,
        "model": config.model_name,
        "collection": collection_name(
            "document_chunk", config.model_name, dimension=config.dimension
        ),
    }
