import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.pipelines import require_local_action
from app.database import get_session
from app.models import (
    ConferenceEdition,
    DocumentAsset,
    ImpactSignal,
    Paper,
    PaperAnalysis,
    PipelineEvent,
    PipelineRun,
)


router = APIRouter(prefix="/api/cognition", tags=["cognition"])
HARNESS_VERSION = "corpus-cognition-v1"


class CorpusScope(BaseModel):
    conference: str = Field(default="CVPR", min_length=1, max_length=40)
    year: int = Field(default=2026, ge=1900, le=2100)


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
    analyses = list(
        session.execute(
            select(
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
    )
    latest_by_paper = {}
    for paper_id, source_sha256, question_set_hash, _ in analyses:
        latest_by_paper.setdefault(
            paper_id, (source_sha256, question_set_hash)
        )
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
        f"{paper_id}:{analysis[0]}:{analysis[1]}"
        for paper_id, analysis in sorted(
            latest_by_paper.items(), key=lambda item: str(item[0])
        )
    ]
    fingerprint = hashlib.sha256("\n".join(fingerprint_parts).encode()).hexdigest()
    return {
        "scope": {"conference": edition.conference, "year": edition.year},
        "edition_id": str(edition.id),
        "coverage": {
            "papers": total,
            "arxiv_links": arxiv,
            "paper_analyses": len(latest_by_paper),
            "likes": likes,
            "local_documents": documents,
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


def _latest_run(session: Session, conference: str, year: int) -> PipelineRun | None:
    return session.scalar(
        select(PipelineRun)
        .where(
            PipelineRun.pipeline == "cognition_harness",
            PipelineRun.config["conference"].as_string() == conference.upper(),
            PipelineRun.config["year"].as_integer() == year,
        )
        .order_by(PipelineRun.created_at.desc())
    )


@router.get("/overview")
def overview(
    conference: str = "CVPR",
    year: int = 2026,
    session: Session = Depends(get_session),
) -> dict:
    snapshot = _snapshot(session, conference, year)
    latest = _latest_run(session, conference, year)
    events = []
    if latest:
        events = list(
            session.scalars(
                select(PipelineEvent)
                .where(PipelineEvent.pipeline_run_id == latest.id)
                .order_by(PipelineEvent.created_at)
            )
        )
    return {
        **snapshot,
        "harness_version": HARNESS_VERSION,
        "latest_run": _run_dict(latest) if latest else None,
        "events": [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "message": event.message,
                "details": event.details,
                "created_at": event.created_at,
            }
            for event in events
        ],
        "stages": [
            {
                "id": "paper_memory",
                "name": "论文认知缓存",
                "status": "SOURCE_READY" if snapshot["coverage"]["paper_analyses"] else "BLOCKED",
                "ready": snapshot["coverage"]["paper_analyses"],
                "total": snapshot["coverage"]["papers"],
                "detail": "复用已有逐篇 AI 问答；输入不变时不重复调用模型。",
            },
            {
                "id": "corpus_discovery",
                "name": "全语料自主发现",
                "status": "NOT_IMPLEMENTED",
                "ready": 0,
                "total": snapshot["coverage"]["papers"],
                "detail": "让模型从全量论文中生成临时研究议程，不预设方法类别。",
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
                message="已有逐篇分析已登记为可复用输入",
                details={
                    "reusable_analyses": snapshot["coverage"]["paper_analyses"],
                    "material_fingerprint": snapshot["material_fingerprint"],
                },
            ),
            PipelineEvent(
                pipeline_run_id=run.id,
                level="INFO",
                event_type="HARNESS_PREPARED",
                message="Harness 控制面已初始化；本步骤没有调用模型",
                details={"next_stage": "corpus_discovery"},
            ),
        ]
    )
    session.commit()
    return {
        "status": "PREPARED",
        "message": "Harness 控制面已初始化；未调用模型。",
        "run": _run_dict(run),
    }
