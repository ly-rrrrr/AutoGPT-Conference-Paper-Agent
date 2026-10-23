import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.job_queue import enqueue_run
from app.lineage_extractor import grobid_ready
from app.models import (
    ConferenceEdition,
    DocumentAsset,
    DocumentAssetRevision,
    DocumentChunk,
    EmbeddingProviderConfig,
    Paper,
    PipelineEvent,
    PipelineRun,
    VectorIndexRecord,
)
from app.storage import RECOMMENDED_FREE_BYTES, save_asset_root, storage_overview
from app.vector_store import milvus_ready
from app.api.pipelines import require_local_action
from app.secret_store import get_secret


router = APIRouter(prefix="/api/infrastructure", tags=["infrastructure"])


class VectorIndexInput(BaseModel):
    config_id: uuid.UUID | None = None
    max_chunks: int = Field(default=500, ge=1, le=5000)
    batch_size: int = Field(default=32, ge=1, le=128)


class StorageInput(BaseModel):
    asset_root: str = Field(min_length=3, max_length=500)


class CorpusInput(BaseModel):
    conference: str = Field(default="CVPR", min_length=2, max_length=40)
    year: int = Field(default=2026, ge=2000, le=2100)
    max_papers: int = Field(default=5000, ge=1, le=5000)


def _edition(session: Session, conference: str, year: int) -> ConferenceEdition:
    edition = session.scalar(
        select(ConferenceEdition).where(
            func.upper(ConferenceEdition.conference) == conference.strip().upper(),
            ConferenceEdition.year == year,
        )
    )
    if edition is None:
        raise HTTPException(status_code=404, detail="会议年度不存在")
    return edition


def _corpus_paper_ids(session: Session, edition_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(Paper.id).where(Paper.conference_edition_id == edition_id)
        )
    )


def _lineage_runs_for_papers(
    session: Session, paper_ids: set[str]
) -> list[PipelineRun]:
    if not paper_ids:
        return []
    return [
        run
        for run in session.scalars(
            select(PipelineRun)
            .where(PipelineRun.pipeline == "lineage")
            .order_by(PipelineRun.created_at.desc())
        )
        if str(run.config.get("paper_id", "")) in paper_ids
    ]


def _corpus_status(session: Session, edition: ConferenceEdition) -> dict:
    paper_ids = _corpus_paper_ids(session, edition.id)
    paper_id_set = set(paper_ids)
    string_ids = {str(item) for item in paper_ids}
    source_ready = session.scalar(
        select(func.count(Paper.id)).where(
            Paper.conference_edition_id == edition.id,
            or_(Paper.pdf_url.is_not(None), Paper.arxiv_id.is_not(None)),
        )
    ) or 0
    asset_rows = (
        session.execute(
            select(DocumentAsset.kind, DocumentAsset.status, func.count(DocumentAsset.id))
            .where(DocumentAsset.paper_id.in_(paper_id_set))
            .group_by(DocumentAsset.kind, DocumentAsset.status)
        ).all()
        if paper_id_set
        else []
    )
    assets = {
        f"{kind}:{asset_status}": count
        for kind, asset_status, count in asset_rows
    }
    vectorized = (
        session.scalar(
            select(func.count(func.distinct(DocumentChunk.paper_id)))
            .join(
                VectorIndexRecord,
                VectorIndexRecord.document_chunk_id == DocumentChunk.id,
            )
            .where(
                DocumentChunk.paper_id.in_(paper_id_set),
                VectorIndexRecord.status == "INDEXED",
            )
        )
        if paper_id_set
        else 0
    )
    runs = _lineage_runs_for_papers(session, string_ids)
    latest_by_paper: dict[str, PipelineRun] = {}
    for run in runs:
        latest_by_paper.setdefault(str(run.config.get("paper_id", "")), run)
    job_counts: dict[str, int] = {}
    for run in latest_by_paper.values():
        job_counts[run.status] = job_counts.get(run.status, 0) + 1
    return {
        "conference": edition.conference,
        "year": edition.year,
        "total": len(paper_ids),
        "source_ready": source_ready,
        "pdf_available": assets.get("pdf:AVAILABLE", 0),
        "parsed": assets.get("grobid_tei:PARSED", 0),
        "failed": assets.get("grobid_tei:FAILED", 0),
        "vectorized": vectorized or 0,
        "jobs": job_counts,
    }


@router.get("/storage")
def get_storage(session: Session = Depends(get_session)) -> dict:
    result = storage_overview()
    result["registered_asset_bytes"] = session.scalar(
        select(func.coalesce(func.sum(DocumentAsset.byte_size), 0))
    ) or 0
    result["registered_assets"] = session.scalar(
        select(func.count(DocumentAsset.id))
    ) or 0
    return result


@router.put("/storage", dependencies=[Depends(require_local_action)])
def update_storage(payload: StorageInput, session: Session = Depends(get_session)) -> dict:
    try:
        result = save_asset_root(payload.asset_root)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    result["registered_asset_bytes"] = session.scalar(
        select(func.coalesce(func.sum(DocumentAsset.byte_size), 0))
    ) or 0
    result["registered_assets"] = session.scalar(
        select(func.count(DocumentAsset.id))
    ) or 0
    result["message"] = "新目录已保存，后续下载和解析立即写入这里；已有文件不会被自动搬移"
    return result


@router.get("/corpus/status")
def corpus_status(
    conference: str = "CVPR",
    year: int = 2026,
    session: Session = Depends(get_session),
) -> dict:
    return _corpus_status(session, _edition(session, conference, year))


@router.post(
    "/corpus/start",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_local_action)],
)
def start_corpus(payload: CorpusInput, session: Session = Depends(get_session)) -> dict:
    storage = storage_overview()
    required_free_bytes = min(
        RECOMMENDED_FREE_BYTES,
        payload.max_papers * 40 * 1024**2,
    )
    if storage["free_bytes"] < required_free_bytes:
        raise HTTPException(
            status_code=409,
            detail=(
                f"当前资产目录空间不足：本批次建议至少预留 "
                f"{required_free_bytes / 1024**3:.1f} GB"
            ),
        )
    edition = _edition(session, payload.conference, payload.year)
    parsed_ids = set(
        session.scalars(
            select(DocumentAsset.paper_id).where(
                DocumentAsset.kind == "grobid_tei",
                DocumentAsset.status == "PARSED",
            )
        )
    )
    papers = list(
        session.scalars(
            select(Paper)
            .where(
                Paper.conference_edition_id == edition.id,
                or_(Paper.pdf_url.is_not(None), Paper.arxiv_id.is_not(None)),
                Paper.id.not_in(parsed_ids),
            )
            .order_by(Paper.id)
            .limit(payload.max_papers)
        )
    )
    paper_ids = {str(paper.id) for paper in papers}
    active_paper_ids: set[str] = set()
    resumed = 0
    for run in _lineage_runs_for_papers(session, paper_ids):
        paper_id = str(run.config.get("paper_id", ""))
        if run.status in {"QUEUED", "RUNNING", "PAUSED"}:
            active_paper_ids.add(paper_id)
        if run.status == "PAUSED":
            run.status = "QUEUED"
            run.available_at = datetime.now(UTC)
            resumed += 1
    queued = 0
    for paper in papers:
        if str(paper.id) in active_paper_ids:
            continue
        enqueue_run(
            session,
            run_key=f"lineage:{paper.id}",
            pipeline="lineage",
            config={"paper_id": str(paper.id)},
            max_attempts=2,
            deduplicate=False,
        )
        queued += 1
    session.commit()
    return {
        "status": "QUEUED",
        "queued": queued,
        "resumed": resumed,
        "message": f"已恢复 {resumed} 篇并新增排队 {queued} 篇；已解析论文自动跳过",
    }


@router.post("/corpus/pause", dependencies=[Depends(require_local_action)])
def pause_corpus(payload: CorpusInput, session: Session = Depends(get_session)) -> dict:
    edition = _edition(session, payload.conference, payload.year)
    paper_ids = {str(item) for item in _corpus_paper_ids(session, edition.id)}
    paused = 0
    for run in _lineage_runs_for_papers(session, paper_ids):
        if run.status != "QUEUED":
            continue
        run.status = "PAUSED"
        session.add(
            PipelineEvent(
                pipeline_run_id=run.id,
                level="INFO",
                event_type="JOB_PAUSED",
                message="批量资产建设已暂停该待执行任务",
                details={"conference": edition.conference, "year": edition.year},
            )
        )
        paused += 1
    session.commit()
    return {
        "status": "PAUSED",
        "paused": paused,
        "message": f"已暂停 {paused} 个待执行任务；正在处理的论文会先完成",
    }


@router.post("/corpus/resume", dependencies=[Depends(require_local_action)])
def resume_corpus(payload: CorpusInput, session: Session = Depends(get_session)) -> dict:
    edition = _edition(session, payload.conference, payload.year)
    paper_ids = {str(item) for item in _corpus_paper_ids(session, edition.id)}
    resumed = 0
    now = datetime.now(UTC)
    for run in _lineage_runs_for_papers(session, paper_ids):
        if run.status != "PAUSED":
            continue
        run.status = "QUEUED"
        run.available_at = now
        session.add(
            PipelineEvent(
                pipeline_run_id=run.id,
                level="INFO",
                event_type="JOB_RESUMED",
                message="批量资产建设已恢复该任务",
                details={"conference": edition.conference, "year": edition.year},
            )
        )
        resumed += 1
    session.commit()
    return {
        "status": "QUEUED",
        "resumed": resumed,
        "message": f"已恢复 {resumed} 个任务",
    }


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
