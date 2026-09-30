import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.pipelines import require_local_action
from app.database import get_session
from app.models import Favorite, Paper, PaperTag, RecentWork, Tag, UserInterest


router = APIRouter(prefix="/api/preferences", tags=["preferences"])
DEFAULT_WEIGHTS = {
    "recent_work": 0.3,
    "interest": 0.25,
    "keyword": 0.2,
    "impact": 0.15,
    "freshness": 0.1,
}


class InterestInput(BaseModel):
    kind: str = Field(pattern="^(interest|keyword)$")
    value: str = Field(min_length=1, max_length=300)
    weight: float = Field(ge=0, le=1)


class RecentWorkInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    abstract: str | None = None
    arxiv_id: str | None = None
    notes: str | None = None


class WeightInput(BaseModel):
    recent_work: float = Field(ge=0, le=1)
    interest: float = Field(ge=0, le=1)
    keyword: float = Field(ge=0, le=1)
    impact: float = Field(ge=0, le=1)
    freshness: float = Field(ge=0, le=1)


def _interest(item: UserInterest) -> dict:
    return {"id": str(item.id), "kind": item.kind, "value": item.value, "weight": item.weight}


@router.get("")
def get_preferences(session: Session = Depends(get_session)) -> dict:
    items = list(session.scalars(select(UserInterest).order_by(UserInterest.created_at)))
    weights = {**DEFAULT_WEIGHTS}
    for item in items:
        if item.kind == "weight" and item.value in weights:
            weights[item.value] = item.weight
    works = list(session.scalars(select(RecentWork).order_by(RecentWork.updated_at.desc())))
    return {
        "interests": [_interest(item) for item in items if item.kind == "interest"],
        "keywords": [_interest(item) for item in items if item.kind == "keyword"],
        "weights": weights,
        "recent_works": [
            {"id": str(work.id), "title": work.title, "abstract": work.abstract, "arxiv_id": work.arxiv_id, "notes": work.notes}
            for work in works
        ],
    }


@router.post("/interests", status_code=201, dependencies=[Depends(require_local_action)])
def add_interest(payload: InterestInput, session: Session = Depends(get_session)) -> dict:
    item = UserInterest(kind=payload.kind, value=payload.value.strip(), weight=payload.weight)
    session.add(item)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="该偏好已经存在") from error
    return _interest(item)


@router.delete("/interests/{item_id}", status_code=204, dependencies=[Depends(require_local_action)])
def delete_interest(item_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
    item = session.get(UserInterest, item_id)
    if item is None or item.kind == "weight":
        raise HTTPException(status_code=404, detail="偏好不存在")
    session.delete(item)


@router.put("/weights", dependencies=[Depends(require_local_action)])
def update_weights(payload: WeightInput, session: Session = Depends(get_session)) -> dict:
    for name, value in payload.model_dump().items():
        item = session.scalar(select(UserInterest).where(UserInterest.kind == "weight", UserInterest.value == name))
        if item is None:
            session.add(UserInterest(kind="weight", value=name, weight=value))
        else:
            item.weight = value
    session.commit()
    return payload.model_dump()


@router.post("/recent-works", status_code=201, dependencies=[Depends(require_local_action)])
def add_recent_work(payload: RecentWorkInput, session: Session = Depends(get_session)) -> dict:
    work = RecentWork(**payload.model_dump())
    session.add(work)
    session.commit()
    return {"id": str(work.id), **payload.model_dump()}


@router.post("/papers/{paper_id}/favorite", status_code=201, dependencies=[Depends(require_local_action)])
def favorite_paper(paper_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    if session.get(Paper, paper_id) is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    favorite = session.scalar(select(Favorite).where(Favorite.paper_id == paper_id))
    if favorite is None:
        favorite = Favorite(paper_id=paper_id)
        session.add(favorite)
        session.commit()
    return {"paper_id": str(paper_id), "favorite": True}


@router.delete("/papers/{paper_id}/favorite", status_code=204, dependencies=[Depends(require_local_action)])
def unfavorite_paper(paper_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
    favorite = session.scalar(select(Favorite).where(Favorite.paper_id == paper_id))
    if favorite:
        session.delete(favorite)


@router.post("/papers/{paper_id}/tags", status_code=201, dependencies=[Depends(require_local_action)])
def tag_paper(paper_id: uuid.UUID, name: str, session: Session = Depends(get_session)) -> dict:
    tag = session.scalar(select(Tag).where(Tag.name == name.strip()))
    if tag is None:
        tag = Tag(name=name.strip())
        session.add(tag)
        session.flush()
    link = session.scalar(select(PaperTag).where(PaperTag.paper_id == paper_id, PaperTag.tag_id == tag.id))
    if link is None:
        session.add(PaperTag(paper_id=paper_id, tag_id=tag.id))
    session.commit()
    return {"paper_id": str(paper_id), "tag": tag.name}
