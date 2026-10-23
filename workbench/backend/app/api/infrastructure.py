import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.job_queue import enqueue_run
from app.lineage_extractor import grobid_ready
from app.models import (
    DocumentAsset,
    DocumentAssetRevision,
    DocumentChunk,
    EmbeddingProviderConfig,
    PipelineRun,
    VectorIndexRecord,
)
from app.vector_store import milvus_ready
from app.api.pipelines import require_local_action
from app.secret_store import get_secret


router = APIRouter(prefix="/api/infrastructure", tags=["infrastructure"])


class VectorIndexInput(BaseModel):
    config_id: uuid.UUID | None = None
    max_chunks: int = Field(default=500, ge=1, le=5000)
    batch_size: int = Field(default=32, ge=1, le=128)


@router.get("/overview")
def overview(session: Session = Depends(get_session)) -> dict:
    embedding_config = session.scalar(
        select(EmbeddingProviderConfig)
        .where(
            EmbeddingProviderConfig.is_default.is_(True),
            EmbeddingProviderConfig.status == "ACTIVE",
        )
        .order_by(EmbeddingProviderConfig.updated_at.desc())
    )
    queue_rows = session.execute(
        select(PipelineRun.status, func.count(PipelineRun.id))
        .where(PipelineRun.pipeline == "lineage")
        .group_by(PipelineRun.status)
    ).all()
    asset_rows = session.execute(
        select(DocumentAsset.kind, DocumentAsset.status, func.count(DocumentAsset.id))
        .group_by(DocumentAsset.kind, DocumentAsset.status)
        .order_by(DocumentAsset.kind, DocumentAsset.status)
    ).all()
    vector_rows = session.execute(
        select(VectorIndexRecord.status, func.count(VectorIndexRecord.id)).group_by(
            VectorIndexRecord.status
        )
    ).all()
    return {
        "services": {
            "postgresql": "ready",
            "milvus": "ready" if milvus_ready() else "unavailable",
            "grobid": "ready" if grobid_ready() else "unavailable",
        },
        "assets": {
            "current": session.scalar(select(func.count(DocumentAsset.id))) or 0,
            "revisions": session.scalar(select(func.count(DocumentAssetRevision.id))) or 0,
            "chunks": session.scalar(select(func.count(DocumentChunk.id))) or 0,
            "by_kind_status": [
                {"kind": kind, "status": status, "count": count}
                for kind, status, count in asset_rows
            ],
        },
        "vectors": {
            "records": session.scalar(select(func.count(VectorIndexRecord.id))) or 0,
            "by_status": {status: count for status, count in vector_rows},
            "embedding_ready": bool(
                embedding_config and get_secret(embedding_config.secret_ref)
            ),
            "embedding_model": embedding_config.model_name if embedding_config else None,
            "embedding_dimension": embedding_config.dimension if embedding_config else None,
        },
        "jobs": {"by_status": {status: count for status, count in queue_rows}},
    }


@router.post(
    "/index/start",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_local_action)],
)
def start_vector_index(
    payload: VectorIndexInput,
    session: Session = Depends(get_session),
) -> dict:
    config = (
        session.get(EmbeddingProviderConfig, payload.config_id)
        if payload.config_id
        else session.scalar(
            select(EmbeddingProviderConfig)
            .where(
                EmbeddingProviderConfig.is_default.is_(True),
                EmbeddingProviderConfig.status == "ACTIVE",
            )
            .order_by(EmbeddingProviderConfig.updated_at.desc())
        )
    )
    if config is None:
        raise HTTPException(status_code=409, detail="请先配置默认 Embedding 模型")
    if not get_secret(config.secret_ref):
        raise HTTPException(status_code=409, detail="Embedding 配置尚未保存 API Key")
    run = enqueue_run(
        session,
        run_key=f"vector-index:{config.id}",
        pipeline="vector_index",
        config={
            "config_id": str(config.id),
            "max_chunks": payload.max_chunks,
            "batch_size": payload.batch_size,
        },
        max_attempts=2,
    )
    session.commit()
    return {
        "status": run.status,
        "run_id": str(run.id),
        "message": "增量向量索引任务已进入可恢复队列",
    }
