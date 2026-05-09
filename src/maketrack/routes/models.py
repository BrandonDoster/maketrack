from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.models.model import Model
from maketrack.schemas.model import ModelCreate, ModelRead, ModelUpdate
from maketrack.services import models as svc
from maketrack.services.uploads import delete_upload

router = APIRouter(prefix="/api/models", tags=["models"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _to_read(row: Model) -> ModelRead:
    return ModelRead(
        id=row.id,
        name=row.name,
        description=row.description,
        source_type=row.source_type,
        source_url=row.source_url,
        notes=row.notes,
        tags=svc.decode_tags(row.tags),
        thumbnail_asset_id=row.thumbnail_asset_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[ModelRead])
async def list_models(
    session: SessionDep,
    tag: str | None = None,
    source_type: str | None = None,
) -> list[ModelRead]:
    rows = await svc.list_models(session, tag=tag, source_type=source_type)
    return [_to_read(r) for r in rows]


@router.get("/{model_id}", response_model=ModelRead)
async def get_model(model_id: int, session: SessionDep) -> ModelRead:
    return _to_read(await svc.get_model(session, model_id))


@router.post("", response_model=ModelRead, status_code=status.HTTP_201_CREATED)
async def create_model(payload: ModelCreate, session: SessionDep) -> ModelRead:
    row = await svc.create_model(session, payload)
    await session.commit()
    await session.refresh(row)
    return _to_read(row)


@router.patch("/{model_id}", response_model=ModelRead)
async def update_model(model_id: int, payload: ModelUpdate, session: SessionDep) -> ModelRead:
    row = await svc.update_model(session, model_id, payload)
    await session.commit()
    await session.refresh(row)
    return _to_read(row)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: int, session: SessionDep) -> None:
    paths = await svc.delete_model(session, model_id)
    await session.commit()
    for path in paths:
        delete_upload(path)
