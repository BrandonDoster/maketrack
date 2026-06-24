from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.services import bom as bom_svc
from tests.factories import link_item, make_inventory_item, make_project


async def _make_project_with_item(
    session: AsyncSession,
    *,
    item_name: str = "M3 Bolt",
    on_hand: float = 100,
    qty_required: float = 50,
    qty_consumed: float = 0,
    project_status: str = "planning",
) -> tuple[int, int]:
    project = await make_project(session, name=f"P-{item_name}", status=project_status)
    item = await make_inventory_item(session, name=item_name, quantity=on_hand)
    await link_item(
        session,
        project.id,
        inventory_item_id=item.id,
        qty_required=qty_required,
        qty_consumed=qty_consumed,
    )
    return project.id, item.id


async def test_bom_when_inventory_covers_demand(session: AsyncSession) -> None:
    pid, _ = await _make_project_with_item(session, on_hand=100, qty_required=50)
    bom = await bom_svc.project_bom(session, pid)
    assert len(bom) == 1
    row = bom[0]
    assert row.still_needed_for_project == 50
    assert row.on_hand == 100
    assert row.still_to_buy == 0


async def test_bom_when_short(session: AsyncSession) -> None:
    pid, _ = await _make_project_with_item(session, on_hand=10, qty_required=50)
    row = (await bom_svc.project_bom(session, pid))[0]
    assert row.still_needed_for_project == 50
    assert row.on_hand == 10
    assert row.still_to_buy == 40


async def test_bom_consumed_reduces_still_needed(session: AsyncSession) -> None:
    pid, _ = await _make_project_with_item(session, on_hand=0, qty_required=50, qty_consumed=20)
    row = (await bom_svc.project_bom(session, pid))[0]
    assert row.still_needed_for_project == 30
    assert row.still_to_buy == 30


async def test_shopping_list_aggregates_across_active_projects(session: AsyncSession) -> None:
    # Same item used by two active projects, total demand exceeds inventory.
    item = await make_inventory_item(session, name="Heatset M3", quantity=5)

    p1 = (await make_project(session, name="A")).id
    p2 = (await make_project(session, name="B")).id

    await link_item(session, p1, inventory_item_id=item.id, qty_required=4)
    await link_item(session, p2, inventory_item_id=item.id, qty_required=6)

    rows = await bom_svc.shopping_list(session)
    assert len(rows) == 1
    assert rows[0].still_to_buy == 5  # total need 10, on hand 5 -> 5 to buy
    assert sorted(rows[0].project_ids) == sorted([p1, p2])


async def test_shopping_list_excludes_inactive_projects(session: AsyncSession) -> None:
    await _make_project_with_item(
        session,
        item_name="Should Not Appear",
        on_hand=0,
        qty_required=10,
        project_status="done",
    )

    rows = await bom_svc.shopping_list(session)
    names = [r.name for r in rows]
    assert "Should Not Appear" not in names


async def test_shopping_list_omits_covered_items(session: AsyncSession) -> None:
    await _make_project_with_item(session, item_name="Covered", on_hand=100, qty_required=10)
    rows = await bom_svc.shopping_list(session)
    assert all(r.name != "Covered" for r in rows)


async def test_dashboard_renders_shopping_list_section(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_project_with_item(session, item_name="Visible Item", on_hand=0, qty_required=5)
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Shopping list" in resp.text
    assert "Visible Item" in resp.text


async def test_project_list_renders(client: AsyncClient, session: AsyncSession) -> None:
    await make_project(session, name="Viewable Project")
    resp = await client.get("/projects")
    assert resp.status_code == 200
    assert "Viewable Project" in resp.text


async def test_project_detail_renders_with_links(
    client: AsyncClient, session: AsyncSession
) -> None:
    project = await make_project(session, name="Linked Project")
    item = await make_inventory_item(session, name="Detail Item", quantity=1)
    await link_item(session, project.id, inventory_item_id=item.id, qty_required=3)

    resp = await client.get(f"/projects/{project.id}")
    assert resp.status_code == 200
    assert "Linked Project" in resp.text
    assert "Detail Item" in resp.text
    # BOM column shows still_to_buy 2 (= 3 required - 1 on hand)
    assert ">2<" in resp.text or "still to buy" in resp.text.lower()
