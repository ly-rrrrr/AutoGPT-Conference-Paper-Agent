import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.pipelines import require_local_action
from app.database import get_session
from app.models import ModelProviderConfig
from app.secret_store import get_secret, set_secret


router = APIRouter(prefix="/api/model-configs", tags=["model-configs"])


class ModelConfigInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=80)
    base_url: HttpUrl
    model_name: str = Field(min_length=1, max_length=160)
    api_key: str | None = Field(default=None, min_length=8, max_length=1000)
    is_default: bool = False


def _serialize(item: ModelProviderConfig) -> dict:
    has_api_key = bool(get_secret(item.secret_ref))
    return {
        "id": str(item.id),
        "name": item.name,
        "provider": item.provider,
        "base_url": item.base_url,
        "model_name": item.model_name,
        "is_default": item.is_default,
        "status": item.status,
        "has_api_key": has_api_key,
        "api_key_mask": "••••••••" if has_api_key else None,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _make_default(session: Session, item: ModelProviderConfig) -> None:
    session.execute(
        update(ModelProviderConfig)
        .where(ModelProviderConfig.id != item.id)
        .values(is_default=False)
    )
    item.is_default = True


@router.get("")
def list_model_configs(session: Session = Depends(get_session)) -> dict:
    items = list(
        session.scalars(
            select(ModelProviderConfig).order_by(
                ModelProviderConfig.is_default.desc(), ModelProviderConfig.created_at
            )
        )
    )
    return {"items": [_serialize(item) for item in items], "total": len(items)}


@router.post("", status_code=201, dependencies=[Depends(require_local_action)])
def create_model_config(
    payload: ModelConfigInput, session: Session = Depends(get_session)
) -> dict:
    item_id = uuid.uuid4()
    item = ModelProviderConfig(
        id=item_id,
        name=payload.name,
        provider=payload.provider,
        base_url=str(payload.base_url).rstrip("/"),
        model_name=payload.model_name,
        secret_ref=str(item_id),
        is_default=payload.is_default,
        status="ACTIVE",
    )
    session.add(item)
    if payload.is_default:
        session.flush()
        _make_default(session, item)
    if payload.api_key:
        set_secret(item.secret_ref, payload.api_key)
    session.commit()
    return _serialize(item)


@router.put(
    "/{config_id}", dependencies=[Depends(require_local_action)]
)
def update_model_config(
    config_id: uuid.UUID,
    payload: ModelConfigInput,
    session: Session = Depends(get_session),
) -> dict:
    item = session.get(ModelProviderConfig, config_id)
    if item is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    item.name = payload.name
    item.provider = payload.provider
    item.base_url = str(payload.base_url).rstrip("/")
    item.model_name = payload.model_name
    if payload.is_default:
        _make_default(session, item)
    elif item.is_default:
        item.is_default = True
    if payload.api_key:
        set_secret(item.secret_ref, payload.api_key)
    session.commit()
    return _serialize(item)
