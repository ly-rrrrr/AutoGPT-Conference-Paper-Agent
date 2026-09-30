from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import (
    ConferenceEdition,
    DocumentAsset,
    ImpactSignal,
    Paper,
    PaperAnalysis,
    PaperAnswer,
    PaperAuthor,
    PaperMapping,
)
from app.schemas import (
    AnalysisDetail,
    AnswerDetail,
    MappingDetail,
    PaginatedPapers,
    PaperDetail,
    PaperListItem,
)


router = APIRouter(prefix="/api/papers", tags=["papers"])


def _latest_mapping(session: Session, paper_id: UUID) -> PaperMapping | None:
    return session.scalar(
        select(PaperMapping)
        .where(PaperMapping.paper_id == paper_id)
        .order_by(PaperMapping.checked_at.desc())
        .limit(1)
    )


def _latest_analysis(session: Session, paper_id: UUID) -> PaperAnalysis | None:
    return session.scalar(
        select(PaperAnalysis)
        .where(PaperAnalysis.paper_id == paper_id)
        .order_by(PaperAnalysis.analyzed_at.desc(), PaperAnalysis.id.desc())
        .limit(1)
    )


def _latest_likes(session: Session, paper_id: UUID) -> float | None:
    return session.scalar(
        select(ImpactSignal.value)
        .where(
            ImpactSignal.paper_id == paper_id,
            ImpactSignal.source == "alphaxiv_likes",
            ImpactSignal.status == "SUCCESS",
        )
        .order_by(ImpactSignal.observed_at.desc(), ImpactSignal.id.desc())
        .limit(1)
    )


def _authors(session: Session, paper_id: UUID) -> list[str]:
    return list(
        session.scalars(
            select(PaperAuthor.name)
            .where(PaperAuthor.paper_id == paper_id)
            .order_by(PaperAuthor.position)
        )
    )


@router.get("", response_model=PaginatedPapers)
def list_papers(
    query: str | None = None,
    conference: str | None = None,
    year: int | None = None,
    topic: str | None = None,
    mapping_status: str | None = None,
    analysis_status: str | None = None,
    sort: str = Query(default="updated_at", pattern="^(updated_at|title|likes)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    session: Session = Depends(get_session),
) -> PaginatedPapers:
    conditions = []
    if query:
        conditions.append(Paper.title.ilike(f"%{query.strip()}%"))
    if conference:
        conditions.append(ConferenceEdition.conference == conference)
    if year:
        conditions.append(ConferenceEdition.year == year)
    if topic:
        conditions.append(Paper.topic == topic)
    if mapping_status:
        conditions.append(
            exists(
                select(PaperMapping.id).where(
                    PaperMapping.paper_id == Paper.id,
                    PaperMapping.status == mapping_status,
                )
            )
        )
    if analysis_status:
        conditions.append(
            exists(
                select(PaperAnalysis.id).where(
                    PaperAnalysis.paper_id == Paper.id,
                    PaperAnalysis.status == analysis_status,
                )
            )
        )
    total = session.scalar(
        select(func.count(Paper.id))
        .join(ConferenceEdition)
        .where(*conditions)
    ) or 0
    statement = select(Paper, ConferenceEdition).join(ConferenceEdition).where(*conditions)
    if sort == "title":
        statement = statement.order_by(Paper.title)
    elif sort == "likes":
        likes = (
            select(func.max(ImpactSignal.value))
            .where(ImpactSignal.paper_id == Paper.id)
            .correlate(Paper)
            .scalar_subquery()
        )
        statement = statement.order_by(likes.desc().nullslast(), Paper.title)
    else:
        statement = statement.order_by(Paper.updated_at.desc(), Paper.title)
    rows = session.execute(
        statement.offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = []
    for paper, edition in rows:
        mapping = _latest_mapping(session, paper.id)
        analysis = _latest_analysis(session, paper.id)
        items.append(
            PaperListItem(
                id=paper.id,
                conference=edition.conference,
                year=edition.year,
                title=paper.title,
                authors=_authors(session, paper.id),
                topic=paper.topic,
                arxiv_id=paper.arxiv_id,
                mapping_status=mapping.status if mapping else None,
                analysis_status=analysis.status if analysis else None,
                likes=_latest_likes(session, paper.id),
                updated_at=paper.updated_at,
            )
        )
    return PaginatedPapers(total=total, page=page, page_size=page_size, items=items)


@router.get("/{paper_id}", response_model=PaperDetail)
def get_paper(
    paper_id: UUID,
    session: Session = Depends(get_session),
) -> PaperDetail:
    row = session.execute(
        select(Paper, ConferenceEdition)
        .join(ConferenceEdition)
        .where(Paper.id == paper_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    paper, edition = row
    mapping = _latest_mapping(session, paper.id)
    analysis = _latest_analysis(session, paper.id)
    answers = []
    if analysis is not None:
        answers = [
            AnswerDetail(
                question=item.question,
                answer=item.answer,
                source_references=item.source_references,
                warnings=item.warnings,
            )
            for item in session.scalars(
                select(PaperAnswer)
                .where(PaperAnswer.analysis_id == analysis.id)
                .order_by(PaperAnswer.position)
            )
        ]
    document = session.scalar(
        select(DocumentAsset)
        .where(DocumentAsset.paper_id == paper.id)
        .order_by(DocumentAsset.updated_at.desc())
        .limit(1)
    )
    return PaperDetail(
        id=paper.id,
        conference=edition.conference,
        year=edition.year,
        title=paper.title,
        authors=_authors(session, paper.id),
        topic=paper.topic,
        detail_url=paper.detail_url,
        pdf_url=paper.pdf_url,
        arxiv_id=paper.arxiv_id,
        arxiv_url=paper.arxiv_url,
        mapping=MappingDetail.model_validate(mapping, from_attributes=True)
        if mapping
        else None,
        analysis=AnalysisDetail(
            status=analysis.status,
            analysis_mode=analysis.analysis_mode,
            questions=analysis.questions,
            payload=analysis.payload,
            error_code=analysis.error_code,
            error_detail=analysis.error_detail,
            model=analysis.model,
            source_path=analysis.source_path,
            source_sha256=analysis.source_sha256,
            answers=answers,
        )
        if analysis
        else None,
        likes=_latest_likes(session, paper.id),
        document={
            "kind": document.kind,
            "status": document.status,
            "path": document.path,
            "parser": document.parser,
            "parser_version": document.parser_version,
            "last_error": document.last_error,
        }
        if document
        else None,
    )

