from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.models.inventory import InventoryItem
from maketrack.models.project import Project, ProjectItem
from maketrack.schemas.project import ACTIVE_STATUSES, BOMRow, ShoppingListRow


async def project_bom(session: AsyncSession, project_id: int) -> list[BOMRow]:
    """For one project: how much we still need to buy of each inventory item.

    still_needed_for_project = qty_required - qty_consumed (clamped at 0)
    on_hand                  = inventory_items.quantity
    still_to_buy             = max(0, still_needed - on_hand)
    """
    rows = (
        await session.execute(
            select(ProjectItem, InventoryItem)
            .join(InventoryItem, InventoryItem.id == ProjectItem.inventory_item_id)
            .where(ProjectItem.project_id == project_id)
            .order_by(InventoryItem.name)
        )
    ).all()
    out: list[BOMRow] = []
    for link, item in rows:
        still_needed = max(0.0, link.qty_required - link.qty_consumed)
        on_hand = item.quantity
        still_to_buy = max(0.0, still_needed - on_hand)
        out.append(
            BOMRow(
                inventory_item_id=item.id,
                name=item.name,
                unit=item.unit,
                still_needed_for_project=still_needed,
                on_hand=on_hand,
                still_to_buy=still_to_buy,
            )
        )
    return out


async def shopping_list(session: AsyncSession) -> list[ShoppingListRow]:
    """Aggregate "still to buy" across every active project.

    Active = status in (planning, printing) per CLAUDE.md. The same item
    referenced by two projects collapses to one row whose still_to_buy is
    the *combined* shortfall, not per-project max.
    """
    rows = (
        await session.execute(
            select(ProjectItem, InventoryItem, Project)
            .join(InventoryItem, InventoryItem.id == ProjectItem.inventory_item_id)
            .join(Project, Project.id == ProjectItem.project_id)
            .where(Project.status.in_(ACTIVE_STATUSES))
        )
    ).all()

    # Sum the still-needed quantities across active projects per item, then
    # subtract on_hand once — running on_hand against per-project shortfalls
    # would let inventory cover the same demand twice.
    needed_by_item: dict[int, float] = defaultdict(float)
    item_meta: dict[int, InventoryItem] = {}
    projects_by_item: dict[int, set[int]] = defaultdict(set)
    for link, item, project in rows:
        still_needed = max(0.0, link.qty_required - link.qty_consumed)
        if still_needed <= 0:
            continue
        needed_by_item[item.id] += still_needed
        item_meta[item.id] = item
        projects_by_item[item.id].add(project.id)

    out: list[ShoppingListRow] = []
    for item_id, needed in needed_by_item.items():
        item = item_meta[item_id]
        still_to_buy = max(0.0, needed - item.quantity)
        if still_to_buy <= 0:
            continue
        out.append(
            ShoppingListRow(
                inventory_item_id=item_id,
                name=item.name,
                unit=item.unit,
                on_hand=item.quantity,
                still_to_buy=still_to_buy,
                project_ids=sorted(projects_by_item[item_id]),
            )
        )
    out.sort(key=lambda r: r.name)
    return out
