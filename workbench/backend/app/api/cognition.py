import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.pipelines import require_local_action
from app.cognition_discovery import DISCOVERY_VERSION, run_corpus_discovery
from app.cognition_workflow import prepare_control_state
from app.database import get_session
from app.models import (
    CognitionArtifact,
    CognitionArtifactSource,
    CognitionPaperMemory,
    ConferenceEdition,
    DocumentAsset,
    ImpactSignal,
    ModelProviderConfig,
    Paper,
    PaperAnalysis,
    PipelineEvent,
    PipelineRun,
)
from app.secret_store import get_secret


router = APIRouter(prefix="/api/cognition", tags=["cognition"])
HARNESS_VERSION = "corpus-cognition-v2"
PAPER_MEMORY_VERSION = "paper-memory-v1"


class CorpusScope(BaseModel):
    conference: str = Field(default="CVPR", min_length=1, max_length=40)
    year: int = Field(default=2026, ge=1900, le=2100)


class DiscoveryStart(CorpusScope):
    max_model_calls: int = Field(default=1, ge=1, le=50)
    papers_per_batch: int = Field(default=12, ge=4, le=30)
    max_input_chars: int = Field(default=60000, ge=20000, le=200000)


def _edition(session: Session, conference: str, year: int) -> ConferenceEdition:
    edition = session.scalar(
        select(ConferenceEdition).where(
            ConferenceEdition.conference == conference.upper(),
            ConferenceEdition.year == year,
        )
    )
    if edition is None:
        raise HTTPException(status_code=404, detail="工作台中没有这个会议年度")
    return edition


def _paper_ids(edition_id: uuid.UUID):
    return select(Paper.id).where(Paper.conference_edition_id == edition_id)


def _latest_analyses(session: Session, paper_ids) -> dict:
    rows = session.execute(
        select(
            PaperAnalysis.id,
            PaperAnalysis.paper_id,
            PaperAnalysis.source_sha256,
            PaperAnalysis.question_set_hash,
            PaperAnalysis.analyzed_at,
        )
        .where(
            PaperAnalysis.paper_id.in_(paper_ids),
            PaperAnalysis.status == "SUCCESS",
        )
        .order_by(PaperAnalysis.paper_id, PaperAnalysis.analyzed_at.desc())
    )
    latest = {}
    for analysis_id, paper_id, source_sha256, question_set_hash, _ in rows:
        latest.setdefault(
            paper_id,
            {
                "analysis_id": analysis_id,
                "source_sha256": source_sha256,
                "question_set_hash": question_set_hash,
            },
        )
    return latest


def _snapshot(session: Session, conference: str, year: int) -> dict:
    edition = _edition(session, conference, year)
    paper_ids = _paper_ids(edition.id)
    total = session.scalar(select(func.count()).select_from(paper_ids.subquery())) or 0
    arxiv = (
        session.scalar(
            select(func.count(Paper.id)).where(
                Paper.conference_edition_id == edition.id,
                Paper.arxiv_id.is_not(None),
            )
        )
        or 0
    )
    latest_by_paper = _latest_analyses(session, paper_ids)
    likes = (
        session.scalar(
            select(func.count(func.distinct(ImpactSignal.paper_id))).where(
                ImpactSignal.paper_id.in_(paper_ids),
                ImpactSignal.status == "SUCCESS",
            )
        )
        or 0
    )
    documents = (
        session.scalar(
            select(func.count(func.distinct(DocumentAsset.paper_id))).where(
                DocumentAsset.paper_id.in_(paper_ids),
                DocumentAsset.path.is_not(None),
            )
        )
        or 0
    )
    fingerprint_parts = [
        f"{paper_id}:{analysis['source_sha256']}:{analysis['question_set_hash']}"
        for paper_id, analysis in sorted(
            latest_by_paper.items(), key=lambda item: str(item[0])
        )
    ]
    fingerprint = hashlib.sha256("\n".join(fingerprint_parts).encode()).hexdigest()
    memory_count = (
        session.scalar(
            select(func.count(CognitionPaperMemory.id)).where(
                CognitionPaperMemory.paper_id.in_(paper_ids),
                CognitionPaperMemory.status == "SOURCE_READY",
                CognitionPaperMemory.program_version == PAPER_MEMORY_VERSION,
            )
        )
        or 0
    )
    artifact_count = (
        session.scalar(
            select(func.count(CognitionArtifact.id)).where(
                CognitionArtifact.scope["conference"].as_string() == edition.conference,
                CognitionArtifact.scope["year"].as_integer() == edition.year,
            )
        )
        or 0
    )
    return {
        "scope": {"conference": edition.conference, "year": edition.year},
        "edition_id": str(edition.id),
        "coverage": {
            "papers": total,
            "arxiv_links": arxiv,
            "paper_analyses": len(latest_by_paper),
            "likes": likes,
            "local_documents": documents,
            "paper_memories": memory_count,
            "cognition_artifacts": artifact_count,
        },
        "gaps": {
            "missing_arxiv": total - arxiv,
            "missing_analysis": total - len(latest_by_paper),
            "missing_local_document": total - documents,
        },
        "material_fingerprint": fingerprint,
    }


def _run_dict(run: PipelineRun) -> dict:
    return {
        "id": str(run.id),
        "external_id": run.external_id,
        "run_key": run.run_key,
        "pipeline": run.pipeline,
        "status": run.status,
        "config": run.config,
        "counters": run.counters,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _latest_run(
    session: Session,
    conference: str,
    year: int,
    pipeline: str = "cognition_harness",
) -> PipelineRun | None:
    return session.scalar(
        select(PipelineRun)
        .where(
            PipelineRun.pipeline == pipeline,
            PipelineRun.config["conference"].as_string() == conference.upper(),
            PipelineRun.config["year"].as_integer() == year,
        )
        .order_by(PipelineRun.created_at.desc())
    )


def _event_dict(event: PipelineEvent) -> dict:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "message": event.message,
        "details": event.details,
        "created_at": event.created_at,
    }


def _run_events(session: Session, run: PipelineRun | None) -> list[dict]:
    if run is None:
        return []
    return [
        _event_dict(event)
        for event in session.scalars(
            select(PipelineEvent)
            .where(PipelineEvent.pipeline_run_id == run.id)
            .order_by(PipelineEvent.created_at)
        )
    ]


def _discovery_artifacts(
    session: Session, conference: str, year: int, limit: int = 20
) -> list[dict]:
    artifacts = list(
        session.scalars(
            select(CognitionArtifact)
            .where(
                CognitionArtifact.artifact_type == "CORPUS_BATCH_OBSERVATION",
                CognitionArtifact.generator_version == DISCOVERY_VERSION,
                CognitionArtifact.scope["conference"].as_string()
                == conference.upper(),
                CognitionArtifact.scope["year"].as_integer() == year,
            )
            .order_by(CognitionArtifact.created_at.desc())
            .limit(limit)
        )
    )
    if not artifacts:
        return []
    sources: dict[uuid.UUID, list[dict]] = {}
    for artifact_id, paper_id, title, arxiv_id in session.execute(
        select(
            CognitionArtifactSource.artifact_id,
            Paper.id,
            Paper.title,
            Paper.arxiv_id,
        )
        .join(Paper, CognitionArtifactSource.paper_id == Paper.id)
        .where(CognitionArtifactSource.artifact_id.in_([item.id for item in artifacts]))
        .order_by(Paper.title)
    ):
        sources.setdefault(artifact_id, []).append(
            {"paper_id": str(paper_id), "title": title, "arxiv_id": arxiv_id}
        )
    return [
        {
            "id": str(artifact.id),
            "artifact_type": artifact.artifact_type,
            "status": artifact.status,
            "narrative": artifact.narrative,
            "content": artifact.content,
            "scope": artifact.scope,
            "model": artifact.model,
            "sources": sources.get(artifact.id, []),
            "created_at": artifact.created_at,
        }
        for artifact in artifacts
    ]


@router.get("/overview")
def overview(
    conference: str = "CVPR",
    year: int = 2026,
    session: Session = Depends(get_session),
) -> dict:
    snapshot = _snapshot(session, conference, year)
    latest = _latest_run(session, conference, year)
    discovery_run = _latest_run(
        session, conference, year, pipeline="cognition_discovery"
    )
    paper_ids = _paper_ids(uuid.UUID(snapshot["edition_id"]))
    discovery_covered = (
        session.scalar(
            select(func.count(func.distinct(CognitionArtifactSource.paper_id)))
            .join(
                CognitionArtifact,
                CognitionArtifactSource.artifact_id == CognitionArtifact.id,
            )
            .where(
                CognitionArtifactSource.paper_id.in_(paper_ids),
                CognitionArtifact.artifact_type == "CORPUS_BATCH_OBSERVATION",
                CognitionArtifact.generator_version == DISCOVERY_VERSION,
            )
        )
        or 0
    )
    model_config = session.scalar(
        select(ModelProviderConfig)
        .where(
            ModelProviderConfig.is_default.is_(True),
            ModelProviderConfig.status == "ACTIVE",
        )
        .order_by(ModelProviderConfig.updated_at.desc())
    )
    model_ready = bool(model_config and get_secret(model_config.secret_ref))
    return {
        **snapshot,
        "harness_version": HARNESS_VERSION,
        "latest_run": _run_dict(latest) if latest else None,
        "discovery_run": _run_dict(discovery_run) if discovery_run else None,
        "model_ready": model_ready,
        "events": _run_events(session, latest),
        "discovery_events": _run_events(session, discovery_run),
        "artifacts": _discovery_artifacts(session, conference, year),
        "stages": [
            {
                "id": "paper_memory",
                "name": "论文认知缓存",
                "status": (
                    "CACHED"
                    if snapshot["coverage"]["paper_memories"]
                    else "SOURCE_READY"
                    if snapshot["coverage"]["paper_analyses"]
                    else "BLOCKED"
                ),
                "ready": snapshot["coverage"]["paper_memories"],
                "total": snapshot["coverage"]["papers"],
                "detail": "复用已有逐篇 AI 问答；输入不变时不重复调用模型。",
            },
            {
                "id": "corpus_discovery",
                "name": "全语料自主发现",
                "status": (
                    discovery_run.status
                    if discovery_run
                    and discovery_run.status in {"RUNNING", "STOP_REQUESTED"}
                    else "COMPLETED"
                    if discovery_covered
                    and discovery_covered
                    >= snapshot["coverage"]["paper_memories"]
                    else "IN_PROGRESS"
                    if discovery_covered
                    else "READY"
                ),
                "ready": discovery_covered,
                "total": snapshot["coverage"]["papers"],
                "detail": "按未覆盖论文记忆分批生成临时研究议程；每批结果都保存来源和缓存键。",
            },
            {
                "id": "evidence_loops",
                "name": "证据与反例回路",
                "status": "NOT_IMPLEMENTED",
                "ready": 0,
                "total": 0,
                "detail": "对候选洞见并行调查支持、反例和跨领域迁移。",
            },
            {
                "id": "living_atlas",
                "name": "持续认知图谱",
                "status": "NOT_IMPLEMENTED",
                "ready": 0,
                "total": 0,
                "detail": "版本化合并洞见，并投影为方法、时间和领域视图。",
            },
        ],
        "roles": [
            {"name": "Reader Pool", "mode": "并行工作池", "purpose": "读取和更新单篇论文认知，不进行无意义的 Agent 对话。"},
            {"name": "Cartographer", "mode": "单 Agent + 工具", "purpose": "观察全量语料并提出可变化的调查方向。"},
            {"name": "Investigators", "mode": "按需多 Agent", "purpose": "围绕候选洞见并行寻找支持、差异和迁移证据。"},
            {"name": "Challenger", "mode": "独立 Agent", "purpose": "主动寻找反例、覆盖偏差和替代解释。"},
            {"name": "Curator", "mode": "单 Agent", "purpose": "合并、拆分、降级或放弃洞见，维护领域认知状态。"},
        ],
    }


@router.post(
    "/prepare",
    dependencies=[Depends(require_local_action)],
)
def prepare_harness(
    payload: CorpusScope,
    session: Session = Depends(get_session),
) -> dict:
    snapshot = _snapshot(session, payload.conference, payload.year)
    latest = _latest_run(session, payload.conference, payload.year)
    if (
        latest
        and latest.status == "PREPARED"
        and latest.config.get("material_fingerprint") == snapshot["material_fingerprint"]
        and latest.config.get("harness_version") == HARNESS_VERSION
    ):
        return {
            "status": "REUSED",
            "message": "论文材料没有变化，已复用现有 Harness 快照；未调用模型。",
            "run": _run_dict(latest),
        }
    now = datetime.now(UTC)
    run = PipelineRun(
        run_key=f"cognition-{payload.conference.lower()}-{payload.year}-{uuid.uuid4().hex[:8]}",
        pipeline="cognition_harness",
        status="PREPARED",
        config={
            **snapshot["scope"],
            "material_fingerprint": snapshot["material_fingerprint"],
            "harness_version": HARNESS_VERSION,
            "orchestrator_candidate": "langgraph",
            "semantic_categories": "emergent",
        },
        counters={
            "papers": snapshot["coverage"]["papers"],
            "reusable_analyses": snapshot["coverage"]["paper_analyses"],
            "model_calls": 0,
            "token_cost": 0,
        },
        started_at=now,
        ended_at=now,
    )
    session.add(run)
    session.flush()
    edition = _edition(session, payload.conference, payload.year)
    paper_ids = list(session.scalars(_paper_ids(edition.id)))
    latest_analyses = _latest_analyses(
        session, select(Paper.id).where(Paper.conference_edition_id == edition.id)
    )
    existing = {
        memory.paper_id: memory
        for memory in session.scalars(
            select(CognitionPaperMemory).where(
                CognitionPaperMemory.paper_id.in_(paper_ids)
            )
        )
    }
    memory_counts = {
        "created": 0,
        "reused": 0,
        "invalidated": 0,
        "missing_source": 0,
    }
    for paper_id in paper_ids:
        analysis = latest_analyses.get(paper_id)
        source_key = (
            f"{paper_id}:{analysis['source_sha256']}:{analysis['question_set_hash']}:{PAPER_MEMORY_VERSION}"
            if analysis
            else f"{paper_id}:missing:{PAPER_MEMORY_VERSION}"
        )
        fingerprint = hashlib.sha256(source_key.encode()).hexdigest()
        status = "SOURCE_READY" if analysis else "MISSING_SOURCE"
        memory = existing.get(paper_id)
        if memory is None:
            session.add(
                CognitionPaperMemory(
                    paper_id=paper_id,
                    analysis_id=analysis["analysis_id"] if analysis else None,
                    last_seen_run_id=run.id,
                    input_fingerprint=fingerprint,
                    program_version=PAPER_MEMORY_VERSION,
                    status=status,
                    reuse_count=0,
                )
            )
            memory_counts["created"] += 1
        elif memory.input_fingerprint == fingerprint:
            memory.last_seen_run_id = run.id
            memory.reuse_count += 1
            memory_counts["reused"] += 1
        else:
            memory.analysis_id = analysis["analysis_id"] if analysis else None
            memory.last_seen_run_id = run.id
            memory.input_fingerprint = fingerprint
            memory.program_version = PAPER_MEMORY_VERSION
            memory.status = status
            memory_counts["invalidated"] += 1
        if analysis is None:
            memory_counts["missing_source"] += 1
    run.counters = {**run.counters, "paper_memory": memory_counts}
    session.flush()
    refreshed_snapshot = _snapshot(session, payload.conference, payload.year)
    control_state = prepare_control_state(refreshed_snapshot)
    run.config = {
        **run.config,
        "control_state": {
            "stage": control_state["stage"],
            "next_stage": control_state["next_stage"],
            "decisions": control_state["decisions"],
        },
    }
    session.add_all(
        [
            PipelineEvent(
                pipeline_run_id=run.id,
                level="INFO",
                event_type="CORPUS_SNAPSHOT_CREATED",
                message="已建立完整会议语料快照",
                details=snapshot["coverage"],
            ),
            PipelineEvent(
                pipeline_run_id=run.id,
                level="INFO",
                event_type="CACHE_PLAN_CREATED",
                message="逐篇分析已登记为版本化论文记忆",
                details={
                    "reusable_analyses": snapshot["coverage"]["paper_analyses"],
                    "material_fingerprint": snapshot["material_fingerprint"],
                    **memory_counts,
                },
            ),
            PipelineEvent(
                pipeline_run_id=run.id,
                level="INFO",
                event_type="HARNESS_PREPARED",
                message="Harness 控制面已初始化；本步骤没有调用模型",
                details=run.config["control_state"],
            ),
        ]
    )
    session.commit()
    return {
        "status": "PREPARED",
        "message": "Harness 控制面已初始化；未调用模型。",
        "run": _run_dict(run),
    }


@router.post(
    "/discovery/start",
    dependencies=[Depends(require_local_action)],
)
def start_discovery(
    payload: DiscoveryStart,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    snapshot = _snapshot(session, payload.conference, payload.year)
    running = session.scalar(
        select(PipelineRun)
        .where(
            PipelineRun.pipeline == "cognition_discovery",
            PipelineRun.status.in_(["RUNNING", "STOP_REQUESTED"]),
            PipelineRun.config["conference"].as_string()
            == payload.conference.upper(),
            PipelineRun.config["year"].as_integer() == payload.year,
        )
        .order_by(PipelineRun.created_at.desc())
    )
    if running:
        raise HTTPException(status_code=409, detail="这个语料范围已有发现任务在运行")
    model_config = session.scalar(
        select(ModelProviderConfig)
        .where(
            ModelProviderConfig.is_default.is_(True),
            ModelProviderConfig.status == "ACTIVE",
        )
        .order_by(ModelProviderConfig.updated_at.desc())
    )
    if model_config is None or not get_secret(model_config.secret_ref):
        raise HTTPException(
            status_code=409,
            detail="默认模型尚未就绪，请先在“系统设置 → 模型配置”保存 API Key",
        )
    if snapshot["coverage"]["paper_memories"] == 0:
        raise HTTPException(
            status_code=409,
            detail="尚未建立论文认知缓存，请先初始化 Harness",
        )
    paper_ids = _paper_ids(uuid.UUID(snapshot["edition_id"]))
    covered = (
        session.scalar(
            select(func.count(func.distinct(CognitionArtifactSource.paper_id)))
            .join(
                CognitionArtifact,
                CognitionArtifactSource.artifact_id == CognitionArtifact.id,
            )
            .where(
                CognitionArtifactSource.paper_id.in_(paper_ids),
                CognitionArtifact.artifact_type == "CORPUS_BATCH_OBSERVATION",
                CognitionArtifact.generator_version == DISCOVERY_VERSION,
            )
        )
        or 0
    )
    if covered >= snapshot["coverage"]["paper_memories"]:
        raise HTTPException(status_code=409, detail="当前可用论文记忆已全部完成发现覆盖")
    now = datetime.now(UTC)
    run = PipelineRun(
        run_key=(
            f"discovery-{payload.conference.lower()}-{payload.year}-"
            f"{uuid.uuid4().hex[:8]}"
        ),
        pipeline="cognition_discovery",
        status="RUNNING",
        config={
            **snapshot["scope"],
            "model_config_id": str(model_config.id),
            "model": model_config.model_name,
            "max_model_calls": payload.max_model_calls,
            "papers_per_batch": payload.papers_per_batch,
            "max_input_chars": payload.max_input_chars,
            "discovery_version": DISCOVERY_VERSION,
        },
        counters={
            "model_calls": 0,
            "artifacts": 0,
            "papers_covered": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        started_at=now,
    )
    session.add(run)
    session.commit()
    background_tasks.add_task(run_corpus_discovery, run.id)
    return {
        "status": "RUNNING",
        "run_id": str(run.id),
        "message": (
            f"已启动发现试运行：最多 {payload.max_model_calls} 次模型调用，"
            f"每批最多 {payload.papers_per_batch} 篇论文。"
        ),
    }


@router.post(
    "/discovery/{run_id}/stop",
    dependencies=[Depends(require_local_action)],
)
def stop_discovery(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> dict:
    run = session.get(PipelineRun, run_id)
    if run is None or run.pipeline != "cognition_discovery":
        raise HTTPException(status_code=404, detail="没有找到这个发现任务")
    if run.status != "RUNNING":
        return {
            "status": run.status,
            "message": "任务已不在运行，无需停止。",
        }
    run.status = "STOP_REQUESTED"
    session.add(
        PipelineEvent(
            pipeline_run_id=run.id,
            level="INFO",
            event_type="DISCOVERY_STOP_REQUESTED",
            message="已请求停止；当前模型调用完成后停止",
            details={},
        )
    )
    session.commit()
    return {
        "status": "STOP_REQUESTED",
        "message": "已请求停止；当前模型调用完成后不会继续下一批。",
    }
