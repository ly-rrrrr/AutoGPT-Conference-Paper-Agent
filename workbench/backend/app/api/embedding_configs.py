import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.pipelines import require_local_action
from app.database import get_session
from app.models import EmbeddingProviderConfig
from app.secret_store import get_secret, set_secret


router = APIRouter(prefix="/api/embedding-configs", tags=["embedding-configs"])


class EmbeddingConfigInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=80)
    base_url: HttpUrl
    model_name: str = Field(min_length=1, max_length=160)
    dimension: int = Field(ge=1, le=65536)
    api_key: str | None = Field(default=None, min_length=8, max_length=1000)
    is_default: bool = False


def serialize_embedding_config(item: EmbeddingProviderConfig) -> dict:
    has_api_key = bool(get_secret(item.secret_ref))
    return {
        "id": str(item.id),
        "name": item.name,
        "provider": item.provider,
        "base_url": item.base_url,
        "model_name": item.model_name,
        "dimension": item.dimension,
        "is_default": item.is_default,
        "status": item.status,
        "has_api_key": has_api_key,
        "api_key_mask": "••••••••" if has_api_key else None,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def make_default(session: Session, item: EmbeddingProviderConfig) -> None:
    session.execute(
        update(EmbeddingProviderConfig)
        .where(EmbeddingProviderConfig.id != item.id)
        .values(is_default=False)
    )
    item.is_default = True


@router.get("")
def list_embedding_configs(session: Session = Depends(get_session)) -> dict:
    items = list(
        session.scalars(
            select(EmbeddingProviderConfig).order_by(
                EmbeddingProviderConfig.is_default.desc(),
                EmbeddingProviderConfig.created_at,
            )
        )
    )
    return {"items": [serialize_embedding_config(item) for item in items], "total": len(items)}


@router.post("", status_code=201, dependencies=[Depends(require_local_action)])
def create_embedding_config(
    payload: EmbeddingConfigInput, session: Session = Depends(get_session)
) -> dict:
    item_id = uuid.uuid4()
    item = EmbeddingProviderConfig(
        id=item_id,
        name=payload.name,
        provider=payload.provider,
        base_url=str(payload.base_url).rstrip("/"),
        model_name=payload.model_name,
        dimension=payload.dimension,
        secret_ref=f"embedding:{item_id}",
        is_default=payload.is_default,
        status="ACTIVE",
    )
    session.add(item)
    if payload.is_default:
        session.flush()
        make_default(session, item)
    if payload.api_key:
        set_secret(item.secret_ref, payload.api_key)
    session.commit()
    return serialize_embedding_config(item)


@router.put("/{config_id}", dependencies=[Depends(require_local_action)])
def update_embedding_config(
    config_id: uuid.UUID,
    payload: EmbeddingConfigInput,
    session: Session = Depends(get_session),
) -> dict:
    item = session.get(EmbeddingProviderConfig, config_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Embedding 配置不存在")
    item.name = payload.name
    item.provider = payload.provider
    item.base_url = str(payload.base_url).rstrip("/")
    item.model_name = payload.model_name
    item.dimension = payload.dimension
    if payload.is_default:
        make_default(session, item)
    elif item.is_default:
        item.is_default = True
    if payload.api_key:
        set_secret(item.secret_ref, payload.api_key)
    session.commit()
    return serialize_embedding_config(item)
