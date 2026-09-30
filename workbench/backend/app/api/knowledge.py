from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
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
    counts: Counter[str] = Counter()
    for paper, document in rows:
        status = document.status if document else "MISSING"
        counts[status] += 1
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
    total = session.query(Paper).count()
    counts["MISSING"] += max(total - len(rows), 0)
    return {"summary": dict(counts), "total": total, "items": items}
