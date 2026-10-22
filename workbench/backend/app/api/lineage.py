import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.api.pipelines import require_local_action
from app.database import get_session
from app.lineage_extractor import execute_lineage_run, grobid_ready
from app.models import (
    ConferenceEdition,
    Paper,
    PaperReference,
    PipelineRun,
    ReferenceWork,
    RelatedWorkEvidence,
)
from app.schemas import (
    LineageAction,
    LineageGraph,
    LineageOverview,
    LineagePapersResponse,
)


router = APIRouter(prefix="/api/lineage", tags=["lineage"])
RELATION_TYPES = {
    "cites",
    "extends",
    "improves",
    "uses",
    "compares_with",
    "differs_from",
    "addresses_gap_of",
}


@router.get("/overview", response_model=LineageOverview)
def overview(session: Session = Depends(get_session)) -> dict:
    relation_rows = session.execute(
        select(RelatedWorkEvidence.relation_type, func.count(RelatedWorkEvidence.id)).group_by(
            RelatedWorkEvidence.relation_type
        )
    ).all()
    paper_count = session.scalar(
        select(func.count(distinct(PaperReference.paper_id)))
    ) or 0
    return {
        "papers_with_lineage": paper_count,
        "reference_works": session.scalar(select(func.count(ReferenceWork.id))) or 0,
        "references": session.scalar(select(func.count(PaperReference.id))) or 0,
        "evidence": session.scalar(select(func.count(RelatedWorkEvidence.id))) or 0,
        "relations": {name: count for name, count in relation_rows},
        "parser": {"name": "GROBID", "ready": grobid_ready()},
    }


@router.get("/papers", response_model=LineagePapersResponse)
def lineage_papers(
    query: str | None = None,
    limit: int = Query(100, ge=1, le=300),
    session: Session = Depends(get_session),
) -> dict:
    reference_count = (
        select(func.count(PaperReference.id))
        .where(PaperReference.paper_id == Paper.id)
        .correlate(Paper)
        .scalar_subquery()
    )
    statement = (
        select(Paper, ConferenceEdition, reference_count.label("reference_count"))
        .join(ConferenceEdition)
        .where(Paper.arxiv_id.is_not(None))
    )
    if query:
        statement = statement.where(Paper.title.ilike(f"%{query.strip()}%"))
    rows = session.execute(
        statement.order_by(reference_count.desc(), Paper.updated_at.desc()).limit(limit)
    ).all()
    return {
        "items": [
            {
                "id": str(paper.id),
                "title": paper.title,
                "conference": edition.conference,
                "year": edition.year,
                "arxiv_id": paper.arxiv_id,
                "pdf_url": paper.pdf_url,
                "reference_count": count,
            }
            for paper, edition, count in rows
        ]
    }


@router.get("/papers/{paper_id}", response_model=LineageGraph)
def paper_lineage(
    paper_id: uuid.UUID,
    relation_type: list[str] | None = Query(default=None),
    limit: int = Query(300, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> dict:
    invalid = set(relation_type or []) - RELATION_TYPES
    if invalid:
        raise HTTPException(status_code=422, detail=f"未知关系类型：{', '.join(sorted(invalid))}")
    center_row = session.execute(
        select(Paper, ConferenceEdition)
        .join(ConferenceEdition)
        .where(Paper.id == paper_id)
    ).one_or_none()
    if center_row is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    paper, edition = center_row
    statement = (
        select(PaperReference, ReferenceWork, RelatedWorkEvidence)
        .join(ReferenceWork, ReferenceWork.id == PaperReference.reference_work_id)
        .join(RelatedWorkEvidence, RelatedWorkEvidence.paper_reference_id == PaperReference.id)
        .where(PaperReference.paper_id == paper_id)
    )
    if relation_type:
        statement = statement.where(RelatedWorkEvidence.relation_type.in_(relation_type))
    rows = session.execute(
        statement.order_by(RelatedWorkEvidence.confidence.desc(), PaperReference.ordinal).limit(limit)
    ).all()
    nodes = {
        f"paper:{paper.id}": {
            "id": f"paper:{paper.id}",
            "kind": "paper",
            "title": paper.title,
            "year": edition.year,
            "venue": edition.conference,
            "arxiv_id": paper.arxiv_id,
            "is_center": True,
        }
    }
    edges = []
    for reference, work, evidence in rows:
        node_id = f"reference:{work.id}"
        nodes[node_id] = {
            "id": node_id,
            "kind": "reference_work",
            "title": work.title,
            "year": work.publication_year,
            "venue": work.venue,
            "doi": work.doi,
            "arxiv_id": work.arxiv_id,
            "linked_paper_id": str(work.linked_paper_id) if work.linked_paper_id else None,
            "is_center": False,
        }
        edges.append(
            {
                "id": str(evidence.id),
                "source": f"paper:{paper.id}",
                "target": node_id,
                "relation_type": evidence.relation_type,
                "confidence": evidence.confidence,
                "status": evidence.status,
                "evidence": {
                    "context": evidence.context_text,
                    "section": evidence.section_title,
                    "page": evidence.page_number,
                    "coordinates": evidence.coordinates,
                    "classifier": evidence.classifier,
                    "classifier_version": evidence.classifier_version,
                    "source_path": evidence.source_path,
                    "source_sha256": evidence.source_sha256,
                    "raw_reference": reference.raw_reference,
                },
            }
        )
    return {
        "center_paper_id": str(paper.id),
        "nodes": list(nodes.values()),
        "edges": edges,
        "truncated": len(rows) == limit,
    }


@router.post(
    "/papers/{paper_id}/extract",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LineageAction,
    dependencies=[Depends(require_local_action)],
)
def start_extraction(
    paper_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    run_key = f"lineage:{paper_id}"
    active = session.scalar(
        select(PipelineRun).where(
            PipelineRun.run_key == run_key,
            PipelineRun.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    if active:
        return {"status": active.status, "run_id": str(active.id), "message": "该论文的谱系任务已在运行"}
    run = PipelineRun(
        run_key=run_key,
        pipeline="lineage",
        status="QUEUED",
        config={"paper_id": str(paper_id)},
        counters={},
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.commit()
    background_tasks.add_task(execute_lineage_run, run.id, paper_id)
    return {"status": "QUEUED", "run_id": str(run.id), "message": "相关工作谱系任务已启动"}
