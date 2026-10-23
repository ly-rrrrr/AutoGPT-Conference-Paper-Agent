import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.pipelines import require_local_action
from app.database import get_session
from app.models import (
    ConferenceEdition,
    DocumentAsset,
    InsightProposal,
    ModelProviderConfig,
    Paper,
    PaperAnalysis,
    PipelineRun,
    ResearchArtifact,
    ResearchArtifactDependency,
    ResearchBrief,
    ResearchEvidenceRef,
)
from app.active_research import run_research_brief
from app.research_runtime import runtime_status
from app.secret_store import get_secret


router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("/runtime")
def get_runtime_status(session: Session = Depends(get_session)) -> dict:
    config = session.scalar(
        select(ModelProviderConfig)
        .where(ModelProviderConfig.is_default.is_(True), ModelProviderConfig.status == "ACTIVE")
        .order_by(ModelProviderConfig.updated_at.desc())
    )
    return runtime_status(bool(config and get_secret(config.secret_ref)))


class ResearchBriefInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    objective: str = Field(min_length=1, max_length=10000)
    scope: dict[str, Any] = Field(default_factory=dict)
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    output_preferences: dict[str, Any] = Field(default_factory=dict)


class ResearchArtifactInput(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=80)
    content: dict[str, Any] = Field(default_factory=dict)
    narrative: str | None = None
    generator: str = Field(min_length=1, max_length=120)
    generator_version: str = Field(min_length=1, max_length=80)
    configuration: dict[str, Any] = Field(default_factory=dict)
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    workflow_run_id: uuid.UUID | None = None
    supersedes_artifact_id: uuid.UUID | None = None
    parent_artifact_ids: list[uuid.UUID] = Field(default_factory=list)


class EvidenceRefInput(BaseModel):
    source_kind: str = Field(min_length=1, max_length=60)
    source_uri: str = Field(min_length=1, max_length=4000)
    paper_id: uuid.UUID | None = None
    document_asset_id: uuid.UUID | None = None
    page_number: int | None = Field(default=None, ge=1)
    section_title: str | None = None
    quote: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)
    source_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    stance: str = Field(pattern="^(SUPPORTS|CHALLENGES|CONTEXT)$")


class InsightProposalInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=1, max_length=20000)
    why_it_matters: str = Field(min_length=1, max_length=10000)
    epistemic_status: str = Field(
        pattern="^(OBSERVED|AUTHOR_CLAIM|INFERRED|SYNTHESIZED)$"
    )
    scope: dict[str, Any] = Field(default_factory=dict)
    counterarguments: list[Any] = Field(default_factory=list)
    open_questions: list[Any] = Field(default_factory=list)
    suggested_view: dict[str, Any] = Field(default_factory=dict)


def _brief(item: ResearchBrief) -> dict:
    return {
        "id": str(item.id),
        "title": item.title,
        "objective": item.objective,
        "scope": item.scope,
        "tool_policy": item.tool_policy,
        "budget": item.budget,
        "output_preferences": item.output_preferences,
        "status": item.status,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _artifact(item: ResearchArtifact) -> dict:
    return {
        "id": str(item.id),
        "brief_id": str(item.research_brief_id),
        "workflow_run_id": str(item.workflow_run_id) if item.workflow_run_id else None,
        "supersedes_artifact_id": (
            str(item.supersedes_artifact_id) if item.supersedes_artifact_id else None
        ),
        "artifact_type": item.artifact_type,
        "status": item.status,
        "content": item.content,
        "narrative": item.narrative,
        "generator": item.generator,
        "generator_version": item.generator_version,
        "configuration": item.configuration,
        "uncertainty": item.uncertainty,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _evidence(item: ResearchEvidenceRef) -> dict:
    return {
        "id": str(item.id),
        "artifact_id": str(item.research_artifact_id),
        "paper_id": str(item.paper_id) if item.paper_id else None,
        "document_asset_id": str(item.document_asset_id) if item.document_asset_id else None,
        "source_kind": item.source_kind,
        "source_uri": item.source_uri,
        "page_number": item.page_number,
        "section_title": item.section_title,
        "quote": item.quote,
        "locator": item.locator,
        "source_sha256": item.source_sha256,
        "stance": item.stance,
    }


def _insight(item: InsightProposal) -> dict:
    return {
        "id": str(item.id),
        "artifact_id": str(item.research_artifact_id),
        "title": item.title,
        "statement": item.statement,
        "why_it_matters": item.why_it_matters,
        "epistemic_status": item.epistemic_status,
        "scope": item.scope,
        "counterarguments": item.counterarguments,
        "open_questions": item.open_questions,
        "suggested_view": item.suggested_view,
        "status": item.status,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/briefs")
def list_briefs(session: Session = Depends(get_session)) -> dict:
    items = list(
        session.scalars(select(ResearchBrief).order_by(ResearchBrief.updated_at.desc()))
    )
    return {"items": [_brief(item) for item in items], "total": len(items)}


@router.post(
    "/briefs", status_code=201, dependencies=[Depends(require_local_action)]
)
def create_brief(
    payload: ResearchBriefInput, session: Session = Depends(get_session)
) -> dict:
    item = ResearchBrief(**payload.model_dump(), status="DRAFT")
    session.add(item)
    session.commit()
    return _brief(item)


@router.put("/briefs/{brief_id}", dependencies=[Depends(require_local_action)])
def update_brief(
    brief_id: uuid.UUID,
    payload: ResearchBriefInput,
    session: Session = Depends(get_session),
) -> dict:
    item = session.get(ResearchBrief, brief_id)
    if item is None:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    if item.status == "RUNNING":
        raise HTTPException(status_code=409, detail="研究任务运行期间不能修改")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    item.status = "DRAFT"
    session.commit()
    return _brief(item)


@router.get("/briefs/{brief_id}")
def get_brief(brief_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    brief = session.get(ResearchBrief, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    paper_scope = select(Paper.id).join(
        ConferenceEdition, Paper.conference_edition_id == ConferenceEdition.id
    )
    conference = brief.scope.get("conference")
    year = brief.scope.get("year")
    if conference:
        paper_scope = paper_scope.where(
            ConferenceEdition.conference == str(conference).upper()
        )
    if year:
        paper_scope = paper_scope.where(ConferenceEdition.year == int(year))
    scoped_papers = paper_scope.subquery()
    paper_count = session.scalar(select(func.count()).select_from(scoped_papers)) or 0
    analysis_count = (
        session.scalar(
            select(func.count(func.distinct(PaperAnalysis.paper_id))).where(
                PaperAnalysis.paper_id.in_(select(scoped_papers.c.id)),
                PaperAnalysis.status == "SUCCESS",
            )
        )
        or 0
    )
    artifacts = list(
        session.scalars(
            select(ResearchArtifact)
            .where(ResearchArtifact.research_brief_id == brief.id)
            .order_by(ResearchArtifact.created_at)
        )
    )
    artifact_ids = [item.id for item in artifacts]
    evidence = []
    insights = []
    dependencies = []
    if artifact_ids:
        evidence = list(
            session.scalars(
                select(ResearchEvidenceRef).where(
                    ResearchEvidenceRef.research_artifact_id.in_(artifact_ids)
                )
            )
        )
        insights = list(
            session.scalars(
                select(InsightProposal).where(
                    InsightProposal.research_artifact_id.in_(artifact_ids)
                )
            )
        )
        dependencies = list(
            session.scalars(
                select(ResearchArtifactDependency).where(
                    ResearchArtifactDependency.child_artifact_id.in_(artifact_ids)
                )
            )
        )
    runs = list(
        session.scalars(
            select(PipelineRun)
            .where(
                PipelineRun.pipeline == "active_research",
                PipelineRun.config["brief_id"].as_string() == str(brief.id),
            )
            .order_by(PipelineRun.created_at.desc())
            .limit(10)
        )
    )
    return {
        **_brief(brief),
        "artifacts": [_artifact(item) for item in artifacts],
        "evidence": [_evidence(item) for item in evidence],
        "insights": [_insight(item) for item in insights],
        "dependencies": [
            {
                "parent_artifact_id": str(item.parent_artifact_id),
                "child_artifact_id": str(item.child_artifact_id),
                "relation": item.relation,
            }
            for item in dependencies
        ],
        "runs": [
            {
                "id": str(item.id),
                "status": item.status,
                "counters": item.counters,
                "started_at": item.started_at,
                "ended_at": item.ended_at,
            }
            for item in runs
        ],
        "coverage": {
            "paper_count": paper_count,
            "analysis_count": analysis_count,
        },
    }


@router.post(
    "/briefs/{brief_id}/run",
    status_code=202,
    dependencies=[Depends(require_local_action)],
)
def start_research_brief(
    brief_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    brief = session.get(ResearchBrief, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    active = session.scalar(
        select(PipelineRun).where(
            PipelineRun.pipeline == "active_research",
            PipelineRun.status.in_(["QUEUED", "RUNNING"]),
            PipelineRun.config["brief_id"].as_string() == str(brief.id),
        )
    )
    if active:
        raise HTTPException(status_code=409, detail="这个研究任务已经在运行")
    config = session.scalar(
        select(ModelProviderConfig)
        .where(ModelProviderConfig.is_default.is_(True), ModelProviderConfig.status == "ACTIVE")
        .order_by(ModelProviderConfig.updated_at.desc())
    )
    if config is None or not get_secret(config.secret_ref):
        raise HTTPException(status_code=409, detail="请先在模型配置中保存默认模型与 API Key")
    now = datetime.now(UTC)
    run = PipelineRun(
        run_key=f"research-{brief.id}-{uuid.uuid4().hex[:8]}",
        pipeline="active_research",
        status="RUNNING",
        config={
            "brief_id": str(brief.id),
            "model_config_id": str(config.id),
            "model": config.model_name,
        },
        counters={},
        started_at=now,
    )
    session.add(run)
    brief.status = "RUNNING"
    session.commit()
    background_tasks.add_task(run_research_brief, brief.id, run.id)
    return {"status": "RUNNING", "run_id": str(run.id), "message": "主动研究已启动"}


@router.post(
    "/briefs/{brief_id}/artifacts",
    status_code=201,
    dependencies=[Depends(require_local_action)],
)
def create_artifact(
    brief_id: uuid.UUID,
    payload: ResearchArtifactInput,
    session: Session = Depends(get_session),
) -> dict:
    if session.get(ResearchBrief, brief_id) is None:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    supersedes = None
    if payload.supersedes_artifact_id:
        supersedes = session.get(ResearchArtifact, payload.supersedes_artifact_id)
        if supersedes is None or supersedes.research_brief_id != brief_id:
            raise HTTPException(status_code=409, detail="被替代制品不属于当前研究任务")
    parents = []
    for parent_id in dict.fromkeys(payload.parent_artifact_ids):
        parent = session.get(ResearchArtifact, parent_id)
        if parent is None or parent.research_brief_id != brief_id:
            raise HTTPException(status_code=409, detail="父制品不属于当前研究任务")
        parents.append(parent)
    values = payload.model_dump(
        exclude={"parent_artifact_ids", "supersedes_artifact_id"}
    )
    item = ResearchArtifact(
        research_brief_id=brief_id,
        supersedes_artifact_id=supersedes.id if supersedes else None,
        status="CANDIDATE",
        **values,
    )
    session.add(item)
    session.flush()
    for parent in parents:
        session.add(
            ResearchArtifactDependency(
                parent_artifact_id=parent.id,
                child_artifact_id=item.id,
                relation="DERIVED_FROM",
            )
        )
    if supersedes:
        supersedes.status = "SUPERSEDED"
    session.commit()
    return _artifact(item)


@router.post(
    "/artifacts/{artifact_id}/evidence",
    status_code=201,
    dependencies=[Depends(require_local_action)],
)
def add_evidence(
    artifact_id: uuid.UUID,
    payload: EvidenceRefInput,
    session: Session = Depends(get_session),
) -> dict:
    if session.get(ResearchArtifact, artifact_id) is None:
        raise HTTPException(status_code=404, detail="研究制品不存在")
    if payload.paper_id and session.get(Paper, payload.paper_id) is None:
        raise HTTPException(status_code=409, detail="证据论文不存在")
    if payload.document_asset_id and session.get(DocumentAsset, payload.document_asset_id) is None:
        raise HTTPException(status_code=409, detail="证据文档不存在")
    item = ResearchEvidenceRef(
        research_artifact_id=artifact_id, **payload.model_dump()
    )
    session.add(item)
    session.commit()
    return _evidence(item)


@router.post(
    "/artifacts/{artifact_id}/insight",
    status_code=201,
    dependencies=[Depends(require_local_action)],
)
def add_insight(
    artifact_id: uuid.UUID,
    payload: InsightProposalInput,
    session: Session = Depends(get_session),
) -> dict:
    artifact = session.get(ResearchArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="研究制品不存在")
    existing = session.scalar(
        select(InsightProposal).where(
            InsightProposal.research_artifact_id == artifact_id
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="该制品已经包含洞察提议")
    item = InsightProposal(
        research_artifact_id=artifact_id,
        status="CANDIDATE",
        **payload.model_dump(),
    )
    session.add(item)
    session.commit()
    return _insight(item)
