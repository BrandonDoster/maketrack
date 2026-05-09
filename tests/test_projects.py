from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    InventoryItemFactory,
    LocalFilamentFactory,
    PrinterFactory,
    persist,
)


async def test_create_project_minimal(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/projects",
        json={"name": "Voron 2.4 Build", "tags": ["voron", "build"]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Voron 2.4 Build"
    assert body["status"] == "planning"
    assert body["tags"] == ["voron", "build"]
    assert body["completed_at"] is None


async def test_status_done_stamps_completed_at(client: AsyncClient) -> None:
    create = await client.post("/api/projects", json={"name": "P"})
    pid = create.json()["id"]
    patch = await client.patch(f"/api/projects/{pid}", json={"status": "done"})
    assert patch.status_code == 200
    assert patch.json()["status"] == "done"
    assert patch.json()["completed_at"] is not None


async def test_status_back_to_planning_clears_completed_at(client: AsyncClient) -> None:
    create = await client.post("/api/projects", json={"name": "P"})
    pid = create.json()["id"]
    await client.patch(f"/api/projects/{pid}", json={"status": "done"})
    patch = await client.patch(f"/api/projects/{pid}", json={"status": "planning"})
    assert patch.json()["completed_at"] is None


async def test_invalid_status_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/projects", json={"name": "P", "status": "shipped"})
    assert resp.status_code == 422


async def test_list_filter_by_status(client: AsyncClient) -> None:
    a = await client.post("/api/projects", json={"name": "Active"})
    await client.patch(f"/api/projects/{a.json()['id']}", json={"status": "printing"})
    await client.post("/api/projects", json={"name": "Idle"})

    resp = await client.get("/api/projects?status=printing")
    assert [p["name"] for p in resp.json()] == ["Active"]


async def test_link_printer(client: AsyncClient, session: AsyncSession) -> None:
    p = await persist(session, PrinterFactory(name="Voron"))
    await session.commit()

    create = await client.post("/api/projects", json={"name": "P", "printer_id": p.id})
    assert create.status_code == 201
    assert create.json()["printer_id"] == p.id


async def test_add_model_link_idempotent(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    model = await client.post("/api/models", json={"name": "M"})
    mid = model.json()["id"]

    first = await client.post(
        f"/api/projects/{pid}/models",
        json={"model_id": mid, "qty_to_print": 2},
    )
    assert first.status_code == 201

    # Re-link with different qty — should not 409 on the composite PK; the
    # service treats it as an upsert.
    second = await client.post(
        f"/api/projects/{pid}/models",
        json={"model_id": mid, "qty_to_print": 5},
    )
    assert second.status_code == 201
    listing = await client.get(f"/api/projects/{pid}/models")
    assert len(listing.json()) == 1
    assert listing.json()[0]["qty_to_print"] == 5


async def test_remove_model_link(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    model = await client.post("/api/models", json={"name": "M"})
    mid = model.json()["id"]
    await client.post(f"/api/projects/{pid}/models", json={"model_id": mid})

    delete = await client.delete(f"/api/projects/{pid}/models/{mid}")
    assert delete.status_code == 204
    listing = await client.get(f"/api/projects/{pid}/models")
    assert listing.json() == []


async def test_filament_link_round_trip(client: AsyncClient, session: AsyncSession) -> None:
    f = await persist(session, LocalFilamentFactory(name="PLA Black"))
    await session.commit()

    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]

    add = await client.post(
        f"/api/projects/{pid}/filaments",
        json={"filament_id": f.id, "est_weight_g": 250, "role": "extruder_0"},
    )
    assert add.status_code == 201
    link_id = add.json()["id"]

    listing = await client.get(f"/api/projects/{pid}/filaments")
    assert len(listing.json()) == 1
    assert listing.json()[0]["role"] == "extruder_0"

    delete = await client.delete(f"/api/projects/{pid}/filaments/{link_id}")
    assert delete.status_code == 204
    assert (await client.get(f"/api/projects/{pid}/filaments")).json() == []


async def test_item_link_decimal_qty(client: AsyncClient, session: AsyncSession) -> None:
    item = await persist(session, InventoryItemFactory(name="XT60 wire", quantity=2, unit="m"))
    await session.commit()

    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]

    add = await client.post(
        f"/api/projects/{pid}/items",
        json={"inventory_item_id": item.id, "qty_required": 1.5},
    )
    assert add.status_code == 201
    assert add.json()["qty_required"] == 1.5
