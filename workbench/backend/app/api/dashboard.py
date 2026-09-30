from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import (
    ConferenceEdition,
    DocumentAsset,
    ImpactSignal,
    ImportBatch,
    Paper,
    PaperAnalysis,
    PaperMapping,
    PipelineRun,
)
from app.schemas import DashboardResponse


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _counts(session: Session, model, field) -> dict[str, int]:
    return {
        str(key): count
        for key, count in session.execute(
            select(field, func.count(model.id)).group_by(field)
        )
    }


@router.get("", response_model=DashboardResponse)
def dashboard(session: Session = Depends(get_session)) -> DashboardResponse:
    conferences = {
        f"{conference} {year}": count
        for conference, year, count in session.execute(
            select(
                ConferenceEdition.conference,
                ConferenceEdition.year,
                func.count(Paper.id),
            )
            .join(Paper)
            .group_by(ConferenceEdition.conference, ConferenceEdition.year)
        )
    }
    active_runs = [
        {
            "id": str(run.id),
            "run_key": run.run_key,
            "pipeline": run.pipeline,
            "status": run.status,
            "started_at": run.started_at,
        }
        for run in session.scalars(
            select(PipelineRun)
            .where(PipelineRun.status.in_(["QUEUED", "RUNNING"]))
            .order_by(PipelineRun.created_at.desc())
        )
    ]
    recent_errors = [
        {
            "paper_id": str(analysis.paper_id),
            "code": analysis.error_code,
            "detail": analysis.error_detail,
        }
        for analysis in session.scalars(
            select(PaperAnalysis)
            .where(PaperAnalysis.status == "FAILED")
            .order_by(PaperAnalysis.id.desc())
            .limit(5)
        )
    ]
    return DashboardResponse(
        papers_total=session.scalar(select(func.count(Paper.id))) or 0,
        conferences=conferences,
        mappings=_counts(session, PaperMapping, PaperMapping.status),
        analyses=_counts(session, PaperAnalysis, PaperAnalysis.status),
        documents=_counts(session, DocumentAsset, DocumentAsset.status),
        likes_success=session.scalar(
            select(func.count(ImpactSignal.id)).where(
                ImpactSignal.source == "alphaxiv_likes",
                ImpactSignal.status == "SUCCESS",
            )
        )
        or 0,
        active_runs=active_runs,
        recent_errors=recent_errors,
        last_import_at=session.scalar(select(func.max(ImportBatch.finished_at))),
    )

