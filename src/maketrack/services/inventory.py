from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.models.inventory import InventoryItem
from maketrack.schemas.inventory import InventoryItemCreate, InventoryItemUpdate


async def list_items(
    session: AsyncSession,
    *,
    category: str | None = None,
    search: str | None = None,
    below_reorder: bool = False,
) -> Sequence[InventoryItem]:
    stmt = select(InventoryItem).order_by(InventoryItem.name)
    if category is not None:
        stmt = stmt.where(InventoryItem.category == category)
    if search:
        stmt = stmt.where(InventoryItem.name.icontains(search))
    if below_reorder:
        # Items where a threshold is set and current quantity is at or below it.
        stmt = stmt.where(InventoryItem.reorder_threshold.is_not(None)).where(
            InventoryItem.quantity <= InventoryItem.reorder_threshold
        )
    return (await session.execute(stmt)).scalars().all()


async def get_item(session: AsyncSession, item_id: int) -> InventoryItem:
    item = await session.get(InventoryItem, item_id)
    if item is None:
        raise NotFoundError("inventory_item", item_id)
    return item


async def create_item(session: AsyncSession, payload: InventoryItemCreate) -> InventoryItem:
    item = InventoryItem(**payload.model_dump())
    session.add(item)
    await session.flush()
    return item


async def update_item(
    session: AsyncSession, item_id: int, payload: InventoryItemUpdate
) -> InventoryItem:
    item = await get_item(session, item_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await session.flush()
    return item


async def delete_item(session: AsyncSession, item_id: int) -> None:
    item = await get_item(session, item_id)
    await session.delete(item)
    await session.flush()
