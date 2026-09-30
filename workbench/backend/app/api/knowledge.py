from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import DocumentAsset, Paper


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/documents")
def documents(limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)) -> dict:
    rows = session.execute(
        select(Paper, DocumentAsset)
        .outerjoin(DocumentAsset, DocumentAsset.paper_id == Paper.id)
        .order_by(Paper.updated_at.desc())
        .limit(limit)
    ).all()
    items = []
    for paper, document in rows:
        status = document.status if document else "MISSING"
        items.append(
            {
                "paper_id": str(paper.id),
                "title": paper.title,
                "status": status,
                "kind": document.kind if document else "pdf",
                "path": document.path if document else None,
                "sha256": document.sha256 if document else None,
                "parser": document.parser if document else None,
                "parser_version": document.parser_version if document else None,
                "last_error": document.last_error if document else None,
            }
        )
    total = session.scalar(select(func.count(Paper.id))) or 0
    summary = {
        str(status): count
        for status, count in session.execute(
            select(DocumentAsset.status, func.count(DocumentAsset.id)).group_by(
                DocumentAsset.status
            )
        )
    }
    documented = session.scalar(select(func.count(func.distinct(DocumentAsset.paper_id)))) or 0
    summary["MISSING"] = summary.get("MISSING", 0) + total - documented
    return {"summary": summary, "total": total, "items": items}
