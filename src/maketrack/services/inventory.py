from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.models.inventory import InventoryItem
from maketrack.schemas.inventory import InventoryItemCreate, InventoryItemUpdate


def _filter_stmt(
    stmt: Select,
    *,
    category: str | None,
    search: str | None,
    below_reorder: bool,
) -> Select:
    if category is not None:
        stmt = stmt.where(InventoryItem.category == category)
    if search:
        stmt = stmt.where(InventoryItem.name.icontains(search))
    if below_reorder:
        stmt = stmt.where(InventoryItem.reorder_threshold.is_not(None)).where(
            InventoryItem.quantity <= InventoryItem.reorder_threshold
        )
    return stmt


async def list_items(
    session: AsyncSession,
    *,
    category: str | None = None,
    search: str | None = None,
    below_reorder: bool = False,
    page: int | None = None,
    page_size: int | None = None,
) -> Sequence[InventoryItem]:
    stmt = _filter_stmt(
        select(InventoryItem).order_by(InventoryItem.name),
        category=category,
        search=search,
        below_reorder=below_reorder,
    )
    if page is not None and page_size is not None:
        stmt = stmt.limit(page_size).offset(max(0, (page - 1) * page_size))
    return (await session.execute(stmt)).scalars().all()


async def count_items(
    session: AsyncSession,
    *,
    category: str | None = None,
    search: str | None = None,
    below_reorder: bool = False,
) -> int:
    base = _filter_stmt(
        select(InventoryItem.id),
        category=category,
        search=search,
        below_reorder=below_reorder,
    )
    return (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()


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
