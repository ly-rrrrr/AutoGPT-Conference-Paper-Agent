import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.pipelines import require_local_action
from app.cognition_synthesis import (
    SYNTHESIS_VERSION,
    _artifact_batch,
    run_method_synthesis,
)
from app.database import get_session
from app.models import (
    CognitionArtifact,
    CognitionArtifactDependency,
    CognitionArtifactSource,
    ModelProviderConfig,
    Paper,
    PipelineEvent,
    PipelineRun,
)
from app.secret_store import get_secret


router = APIRouter(prefix="/api/atlas", tags=["method-atlas"])


class SynthesisStart(BaseModel):
    conference: str = Field(default="CVPR", min_length=1, max_length=40)
    year: int = Field(default=2026, ge=1900, le=2100)
    max_rounds: int = Field(default=1, ge=1, le=50)
    artifacts_per_round: int = Field(default=8, ge=3, le=30)
    max_input_chars: int = Field(default=100000, ge=30000, le=300000)


class InsightStatusUpdate(BaseModel):
    status: str


def _latest_run(session: Session, conference: str, year: int) -> PipelineRun | None:
    return session.scalar(
        select(PipelineRun)
        .where(
            PipelineRun.pipeline == "cognition_synthesis",
            PipelineRun.config["conference"].as_string() == conference.upper(),
            PipelineRun.config["year"].as_integer() == year,
        )
        .order_by(PipelineRun.created_at.desc())
    )


def _run_dict(run: PipelineRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": str(run.id),
        "run_key": run.run_key,
        "pipeline": run.pipeline,
        "status": run.status,
        "config": run.config,
        "counters": run.counters,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "created_at": run.created_at,
    }


def _events(session: Session, run: PipelineRun | None) -> list[dict]:
    if run is None:
        return []
    return [
        {
            "id": str(event.id),
            "event_type": event.event_type,
            "message": event.message,
            "details": event.details,
            "created_at": event.created_at,
        }
        for event in session.scalars(
            select(PipelineEvent)
            .where(PipelineEvent.pipeline_run_id == run.id)
            .order_by(PipelineEvent.created_at)
        )
    ]


def _insight_query(conference: str, year: int):
    return select(CognitionArtifact).where(
        CognitionArtifact.artifact_type == "METHOD_INSIGHT",
        CognitionArtifact.generator_version == SYNTHESIS_VERSION,
        CognitionArtifact.scope["conference"].as_string() == conference.upper(),
        CognitionArtifact.scope["year"].as_integer() == year,
    )


def _serialize_insights(session: Session, insights: list[CognitionArtifact]) -> list[dict]:
    if not insights:
        return []
    sources: dict[uuid.UUID, list[dict]] = {}
    for artifact_id, paper_id, title, arxiv_id, stance in session.execute(
        select(
            CognitionArtifactSource.artifact_id,
            Paper.id,
            Paper.title,
            Paper.arxiv_id,
            CognitionArtifactSource.stance,
        )
        .join(Paper, CognitionArtifactSource.paper_id == Paper.id)
        .where(CognitionArtifactSource.artifact_id.in_([item.id for item in insights]))
        .order_by(CognitionArtifactSource.stance, Paper.title)
    ):
        sources.setdefault(artifact_id, []).append(
            {
                "paper_id": str(paper_id),
                "title": title,
                "arxiv_id": arxiv_id,
                "stance": stance,
            }
        )
    return [
        {
            "id": str(item.id),
            "status": item.status,
            "title": item.content.get("title", "未命名认知"),
            "claim": item.content.get("claim", item.narrative),
            "mechanism": item.content.get("mechanism"),
            "problem_pressure": item.content.get("problem_pressure"),
            "borrowed_idea": item.content.get("borrowed_idea"),
            "adaptation": item.content.get("adaptation"),
            "domains": item.content.get("domains", []),
            "transfer_targets": item.content.get("transfer_targets", []),
            "counterargument": item.content.get("counterargument"),
            "evidence_boundary": item.content.get("evidence_boundary"),
            "open_questions": item.content.get("open_questions", []),
            "confidence": item.content.get("confidence", 0),
            "sources": sources.get(item.id, []),
            "model": item.model,
            "created_at": item.created_at,
        }
        for item in insights
    ]


@router.get("/overview")
def atlas_overview(
    conference: str = "CVPR",
    year: int = 2026,
    session: Session = Depends(get_session),
) -> dict:
    discovery_total = (
        session.scalar(
            select(func.count(CognitionArtifact.id)).where(
                CognitionArtifact.artifact_type == "CORPUS_BATCH_OBSERVATION",
                CognitionArtifact.scope["conference"].as_string()
                == conference.upper(),
                CognitionArtifact.scope["year"].as_integer() == year,
            )
        )
        or 0
    )
    consumed = (
        session.scalar(
            select(
                func.count(
                    func.distinct(CognitionArtifactDependency.depends_on_artifact_id)
                )
            )
            .join(
                CognitionArtifact,
                CognitionArtifactDependency.artifact_id == CognitionArtifact.id,
            )
            .where(
                CognitionArtifact.artifact_type == "METHOD_INSIGHT",
                CognitionArtifact.generator_version == SYNTHESIS_VERSION,
                CognitionArtifact.scope["conference"].as_string()
                == conference.upper(),
                CognitionArtifact.scope["year"].as_integer() == year,
            )
        )
        or 0
    )
    insights = list(session.scalars(_insight_query(conference, year)))
    latest = _latest_run(session, conference, year)
    model_config = session.scalar(
        select(ModelProviderConfig)
        .where(
            ModelProviderConfig.is_default.is_(True),
            ModelProviderConfig.status == "ACTIVE",
        )
        .order_by(ModelProviderConfig.updated_at.desc())
    )
    domains = {
        str(domain)
        for insight in insights
        for domain in insight.content.get("domains", [])
        if domain
    }
    mechanisms = {
        str(insight.content.get("mechanism"))
        for insight in insights
        if insight.content.get("mechanism")
    }
    return {
        "scope": {"conference": conference.upper(), "year": year},
        "model_ready": bool(model_config and get_secret(model_config.secret_ref)),
        "discovery_artifacts": discovery_total,
        "consumed_discovery_artifacts": consumed,
        "remaining_discovery_artifacts": max(0, discovery_total - consumed),
        "insights": len(insights),
        "challenged": sum(item.status == "CHALLENGED" for item in insights),
        "published": sum(item.status == "PUBLISHED" for item in insights),
        "domains": len(domains),
        "mechanisms": len(mechanisms),
        "latest_run": _run_dict(latest),
        "events": _events(session, latest),
    }


@router.get("/insights")
def list_insights(
    conference: str = "CVPR",
    year: int = 2026,
    status: str | None = None,
    domain: str | None = None,
    query: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    statement = _insight_query(conference, year).order_by(
        CognitionArtifact.created_at.desc()
    )
    if status:
        statement = statement.where(CognitionArtifact.status == status.upper())
    insights = list(session.scalars(statement))
    if domain:
        wanted = domain.casefold()
        insights = [
            item
            for item in insights
            if wanted in {str(value).casefold() for value in item.content.get("domains", [])}
        ]
    if query:
        needle = query.casefold()
        insights = [
            item
            for item in insights
            if needle
            in " ".join(
                str(item.content.get(key, ""))
                for key in ("title", "claim", "mechanism", "problem_pressure")
            ).casefold()
        ]
    return {"items": _serialize_insights(session, insights), "total": len(insights)}


@router.get("/graph")
def atlas_graph(
    conference: str = "CVPR",
    year: int = 2026,
    session: Session = Depends(get_session),
) -> dict:
    insights = _serialize_insights(
        session,
        list(
            session.scalars(
                _insight_query(conference, year).where(
                    CognitionArtifact.status != "ARCHIVED"
                )
            )
        ),
    )
    nodes = []
    edges = []
    axis_nodes = set()
    for insight in insights:
        insight_node = f"insight:{insight['id']}"
        nodes.append(
            {
                "id": insight_node,
                "kind": "insight",
                "label": insight["title"],
                "artifact_id": insight["id"],
                "status": insight["status"],
                "confidence": insight["confidence"],
            }
        )
        axes = [
            ("mechanism", insight["mechanism"]),
            ("pressure", insight["problem_pressure"]),
            *[("domain", value) for value in insight["domains"]],
            *[("transfer", value) for value in insight["transfer_targets"]],
        ]
        for kind, value in axes:
            if not value:
                continue
            axis_id = f"{kind}:{hashlib.sha1(str(value).encode()).hexdigest()[:12]}"
            if axis_id not in axis_nodes:
                axis_nodes.add(axis_id)
                nodes.append(
                    {"id": axis_id, "kind": kind, "label": str(value)}
                )
            edges.append(
                {
                    "id": f"{insight_node}:{axis_id}",
                    "source": insight_node,
                    "target": axis_id,
                    "relation": kind,
                }
            )
    return {"nodes": nodes, "edges": edges, "insights": len(insights)}


@router.post(
    "/synthesis/start", dependencies=[Depends(require_local_action)]
)
def start_synthesis(
    payload: SynthesisStart,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    running = session.scalar(
        select(PipelineRun).where(
            PipelineRun.pipeline == "cognition_synthesis",
            PipelineRun.status.in_(["RUNNING", "STOP_REQUESTED"]),
            PipelineRun.config["conference"].as_string()
            == payload.conference.upper(),
            PipelineRun.config["year"].as_integer() == payload.year,
        )
    )
    if running:
        raise HTTPException(status_code=409, detail="方法综合任务已经在运行")
    model_config = session.scalar(
        select(ModelProviderConfig)
        .where(
            ModelProviderConfig.is_default.is_(True),
            ModelProviderConfig.status == "ACTIVE",
        )
        .order_by(ModelProviderConfig.updated_at.desc())
    )
    if model_config is None or not get_secret(model_config.secret_ref):
        raise HTTPException(status_code=409, detail="默认模型尚未就绪")
    available = session.scalar(
        select(func.count(CognitionArtifact.id)).where(
            CognitionArtifact.artifact_type == "CORPUS_BATCH_OBSERVATION",
            CognitionArtifact.scope["conference"].as_string()
            == payload.conference.upper(),
            CognitionArtifact.scope["year"].as_integer() == payload.year,
        )
    )
    if not available:
        raise HTTPException(status_code=409, detail="尚无批次观察，请先运行全语料自主发现")
    if not _artifact_batch(
        session, payload.conference.upper(), payload.year, 1
    ):
        raise HTTPException(status_code=409, detail="现有批次观察已全部完成方法综合")
    run = PipelineRun(
        run_key=(
            f"synthesis-{payload.conference.lower()}-{payload.year}-"
            f"{uuid.uuid4().hex[:8]}"
        ),
        pipeline="cognition_synthesis",
        status="RUNNING",
        config={
            "conference": payload.conference.upper(),
            "year": payload.year,
            "model_config_id": str(model_config.id),
            "model": model_config.model_name,
            "max_rounds": payload.max_rounds,
            "artifacts_per_round": payload.artifacts_per_round,
            "max_input_chars": payload.max_input_chars,
            "synthesis_version": SYNTHESIS_VERSION,
            "agents": ["Cartographer", "Challenger", "Curator"],
        },
        counters={
            "model_calls": 0,
            "insights_created": 0,
            "observation_artifacts_consumed": 0,
            "total_tokens": 0,
        },
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.commit()
    background_tasks.add_task(run_method_synthesis, run.id)
    return {
        "status": "RUNNING",
        "run_id": str(run.id),
        "message": (
            f"已启动方法综合：最多 {payload.max_rounds} 轮，"
            f"最多 {payload.max_rounds * 3} 次模型调用。"
        ),
    }


@router.post(
    "/synthesis/{run_id}/stop", dependencies=[Depends(require_local_action)]
)
def stop_synthesis(run_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    run = session.get(PipelineRun, run_id)
    if run is None or run.pipeline != "cognition_synthesis":
        raise HTTPException(status_code=404, detail="没有找到这个方法综合任务")
    if run.status == "RUNNING":
        run.status = "STOP_REQUESTED"
        session.add(
            PipelineEvent(
                pipeline_run_id=run.id,
                level="INFO",
                event_type="SYNTHESIS_STOP_REQUESTED",
                message="已请求停止；当前综合轮次完成后停止",
                details={},
            )
        )
        session.commit()
    return {"status": run.status, "message": "停止请求已记录"}


@router.patch(
    "/insights/{insight_id}/status", dependencies=[Depends(require_local_action)]
)
def update_insight_status(
    insight_id: uuid.UUID,
    payload: InsightStatusUpdate,
    session: Session = Depends(get_session),
) -> dict:
    allowed = {"CHALLENGED", "PUBLISHED", "ARCHIVED"}
    status = payload.status.upper()
    if status not in allowed:
        raise HTTPException(status_code=422, detail="不支持的认知制品状态")
    insight = session.get(CognitionArtifact, insight_id)
    if insight is None or insight.artifact_type != "METHOD_INSIGHT":
        raise HTTPException(status_code=404, detail="没有找到这个方法认知制品")
    insight.status = status
    session.commit()
    return {"id": str(insight.id), "status": insight.status}
