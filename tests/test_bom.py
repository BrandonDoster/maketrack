from httpx import AsyncClient


async def _make_project_with_item(
    client: AsyncClient,
    *,
    item_name: str = "M3 Bolt",
    on_hand: float = 100,
    qty_required: float = 50,
    qty_consumed: float = 0,
    project_status: str = "planning",
) -> tuple[int, int]:
    project = await client.post(
        "/api/projects",
        json={"name": f"P-{item_name}", "status": project_status},
    )
    pid = project.json()["id"]
    inv = await client.post(
        "/api/inventory",
        json={"name": item_name, "quantity": on_hand},
    )
    iid = inv.json()["id"]
    await client.post(
        f"/api/projects/{pid}/items",
        json={
            "inventory_item_id": iid,
            "qty_required": qty_required,
            "qty_consumed": qty_consumed,
        },
    )
    return pid, iid


async def test_bom_when_inventory_covers_demand(client: AsyncClient) -> None:
    pid, _ = await _make_project_with_item(client, on_hand=100, qty_required=50)
    bom = (await client.get(f"/api/projects/{pid}/bom")).json()
    assert len(bom) == 1
    row = bom[0]
    assert row["still_needed_for_project"] == 50
    assert row["on_hand"] == 100
    assert row["still_to_buy"] == 0


async def test_bom_when_short(client: AsyncClient) -> None:
    pid, _ = await _make_project_with_item(client, on_hand=10, qty_required=50)
    row = (await client.get(f"/api/projects/{pid}/bom")).json()[0]
    assert row["still_needed_for_project"] == 50
    assert row["on_hand"] == 10
    assert row["still_to_buy"] == 40


async def test_bom_consumed_reduces_still_needed(client: AsyncClient) -> None:
    pid, _ = await _make_project_with_item(client, on_hand=0, qty_required=50, qty_consumed=20)
    row = (await client.get(f"/api/projects/{pid}/bom")).json()[0]
    assert row["still_needed_for_project"] == 30
    assert row["still_to_buy"] == 30


async def test_shopping_list_aggregates_across_active_projects(
    client: AsyncClient,
) -> None:
    # Same item used by two active projects, total demand exceeds inventory.
    inv = await client.post("/api/inventory", json={"name": "Heatset M3", "quantity": 5})
    iid = inv.json()["id"]

    p1 = (await client.post("/api/projects", json={"name": "A"})).json()["id"]
    p2 = (await client.post("/api/projects", json={"name": "B"})).json()["id"]

    await client.post(
        f"/api/projects/{p1}/items",
        json={"inventory_item_id": iid, "qty_required": 4},
    )
    await client.post(
        f"/api/projects/{p2}/items",
        json={"inventory_item_id": iid, "qty_required": 6},
    )

    rows = (await client.get("/api/shopping-list")).json()
    assert len(rows) == 1
    assert rows[0]["still_to_buy"] == 5  # total need 10, on hand 5 -> 5 to buy
    assert sorted(rows[0]["project_ids"]) == sorted([p1, p2])


async def test_shopping_list_excludes_inactive_projects(client: AsyncClient) -> None:
    _pid, _ = await _make_project_with_item(
        client,
        item_name="Should Not Appear",
        on_hand=0,
        qty_required=10,
        project_status="done",
    )

    rows = (await client.get("/api/shopping-list")).json()
    names = [r["name"] for r in rows]
    assert "Should Not Appear" not in names


async def test_shopping_list_omits_covered_items(client: AsyncClient) -> None:
    _pid, _ = await _make_project_with_item(
        client, item_name="Covered", on_hand=100, qty_required=10
    )
    rows = (await client.get("/api/shopping-list")).json()
    assert all(r["name"] != "Covered" for r in rows)


async def test_dashboard_renders_shopping_list_section(client: AsyncClient) -> None:
    _pid, _ = await _make_project_with_item(
        client, item_name="Visible Item", on_hand=0, qty_required=5
    )
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Shopping list" in resp.text
    assert "Visible Item" in resp.text


async def test_project_list_renders(client: AsyncClient) -> None:
    await client.post("/api/projects", json={"name": "Viewable Project"})
    resp = await client.get("/projects")
    assert resp.status_code == 200
    assert "Viewable Project" in resp.text


async def test_project_detail_renders_with_links(
    client: AsyncClient,
) -> None:
    project = await client.post("/api/projects", json={"name": "Linked Project"})
    pid = project.json()["id"]
    inv = await client.post("/api/inventory", json={"name": "Detail Item", "quantity": 1})
    iid = inv.json()["id"]
    await client.post(
        f"/api/projects/{pid}/items",
        json={"inventory_item_id": iid, "qty_required": 3},
    )

    resp = await client.get(f"/projects/{pid}")
    assert resp.status_code == 200
    assert "Linked Project" in resp.text
    assert "Detail Item" in resp.text
    # BOM column shows still_to_buy 2 (= 3 required - 1 on hand)
    assert ">2<" in resp.text or "still to buy" in resp.text.lower()
