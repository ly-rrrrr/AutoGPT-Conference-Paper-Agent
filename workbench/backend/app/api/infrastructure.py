from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.lineage_extractor import grobid_ready
from app.models import (
    DocumentAsset,
    DocumentAssetRevision,
    DocumentChunk,
    PipelineRun,
    VectorIndexRecord,
)
from app.vector_store import milvus_ready


router = APIRouter(prefix="/api/infrastructure", tags=["infrastructure"])


@router.get("/overview")
def overview(session: Session = Depends(get_session)) -> dict:
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
        },
        "jobs": {"by_status": {status: count for status, count in queue_rows}},
    }
