from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import get_session
from maketrack.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
)
from maketrack.services import inventory as svc

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[InventoryItemRead])
async def list_items(session: SessionDep, category: str | None = None) -> list[InventoryItemRead]:
    rows = await svc.list_items(session, category=category)
    return [InventoryItemRead.model_validate(r) for r in rows]


@router.get("/{item_id}", response_model=InventoryItemRead)
async def get_item(item_id: int, session: SessionDep) -> InventoryItemRead:
    return InventoryItemRead.model_validate(await svc.get_item(session, item_id))


@router.post("", response_model=InventoryItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(payload: InventoryItemCreate, session: SessionDep) -> InventoryItemRead:
    row = await svc.create_item(session, payload)
    await session.commit()
    await session.refresh(row)
    return InventoryItemRead.model_validate(row)


@router.patch("/{item_id}", response_model=InventoryItemRead)
async def update_item(
    item_id: int, payload: InventoryItemUpdate, session: SessionDep
) -> InventoryItemRead:
    row = await svc.update_item(session, item_id, payload)
    await session.commit()
    await session.refresh(row)
    return InventoryItemRead.model_validate(row)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int, session: SessionDep) -> None:
    await svc.delete_item(session, item_id)
    await session.commit()
