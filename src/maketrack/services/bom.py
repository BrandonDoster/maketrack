from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.models.inventory import InventoryItem
from maketrack.models.project import Project, ProjectItem
from maketrack.schemas.project import ACTIVE_STATUSES, BOMRow, ShoppingListRow


async def project_bom(session: AsyncSession, project_id: int) -> list[BOMRow]:
    """For one project: how much we still need to buy of each BOM row.

    For linked rows:
      still_needed = qty_required - qty_consumed (clamped at 0)
      on_hand      = inventory_items.quantity
      still_to_buy = max(0, still_needed - on_hand)

    For unlinked custom rows we don't know inventory state, so:
      still_to_buy = still_needed
      on_hand      = NULL
    """
    rows = (
        await session.execute(
            select(ProjectItem, InventoryItem)
            .outerjoin(InventoryItem, InventoryItem.id == ProjectItem.inventory_item_id)
            .where(ProjectItem.project_id == project_id)
            .order_by(InventoryItem.name.asc().nulls_last(), ProjectItem.name, ProjectItem.id)
        )
    ).all()
    out: list[BOMRow] = []
    for link, item in rows:
        still_needed = max(0.0, link.qty_required - link.qty_consumed)
        if item is not None:
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
                    project_item_id=link.id,
                )
            )
        else:
            out.append(
                BOMRow(
                    inventory_item_id=None,
                    name=link.name or "(unnamed)",
                    unit=link.unit,
                    still_needed_for_project=still_needed,
                    on_hand=None,
                    still_to_buy=still_needed,
                    project_item_id=link.id,
                )
            )
    return out


async def shopping_list(session: AsyncSession) -> list[ShoppingListRow]:
    """Aggregate "still to buy" across every active project.

    Linked items: sum still_needed across active projects, then subtract
    on_hand once.
    Unlinked items: each typed-name row contributes its full still_needed
    independently — we can't dedupe by name reliably (different projects
    may type "M3x12 SHCS" vs "M3 12mm SHCS").
    """
    rows = (
        await session.execute(
            select(ProjectItem, InventoryItem, Project)
            .outerjoin(InventoryItem, InventoryItem.id == ProjectItem.inventory_item_id)
            .join(Project, Project.id == ProjectItem.project_id)
            .where(Project.status.in_(ACTIVE_STATUSES))
        )
    ).all()

    # Aggregate the linked side first; the unlinked side stays per-row.
    needed_by_item: dict[int, float] = defaultdict(float)
    item_meta: dict[int, InventoryItem] = {}
    projects_by_item: dict[int, set[int]] = defaultdict(set)
    unlinked: list[ShoppingListRow] = []

    for link, item, project in rows:
        still_needed = max(0.0, link.qty_required - link.qty_consumed)
        if still_needed <= 0:
            continue
        if item is not None:
            needed_by_item[item.id] += still_needed
            item_meta[item.id] = item
            projects_by_item[item.id].add(project.id)
        else:
            unlinked.append(
                ShoppingListRow(
                    inventory_item_id=None,
                    name=link.name or "(unnamed)",
                    unit=link.unit,
                    on_hand=0.0,
                    still_to_buy=still_needed,
                    project_ids=[project.id],
                )
            )

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
    out.extend(unlinked)
    out.sort(key=lambda r: r.name)
    return out
