from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    InventoryItemFactory,
    LocalFilamentFactory,
    PrinterFactory,
    persist,
)

# ── UI: read/edit toggle and draft-create flow ────────────────────────────


async def test_new_project_button_creates_draft_in_edit_mode(client: AsyncClient) -> None:
    """Mirror of printers/models — '+ New project' POSTs to /projects/new,
    creates a stub named 'New project', and drops the user on the detail
    page in edit mode."""
    resp = await client.post("/projects/new", follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/projects/")
    assert location.endswith("?edit=true")

    detail = await client.get(location)
    assert detail.status_code == 200
    assert 'value="New project"' in detail.text
    assert "Done editing" in detail.text
    assert "Delete project" in detail.text


async def test_project_detail_read_mode_hides_edit_affordances(client: AsyncClient) -> None:
    create = await client.post("/api/projects", json={"name": "P"})
    pid = create.json()["id"]

    read = await client.get(f"/projects/{pid}")
    # No basic-field inputs in read mode.
    assert 'name="name"' not in read.text
    # Edit toggle entry.
    assert "Edit page" in read.text


async def test_project_detail_edit_mode_reveals_form(client: AsyncClient) -> None:
    create = await client.post("/api/projects", json={"name": "Editable"})
    pid = create.json()["id"]

    edit = await client.get(f"/projects/{pid}?edit=true")
    assert 'value="Editable"' in edit.text
    assert "Done editing" in edit.text
    # Photos upload forms appear in edit mode.
    assert f'action="/projects/{pid}/photo/cover"' in edit.text


async def test_done_editing_saves_and_exits_read_mode(client: AsyncClient) -> None:
    create = await client.post("/projects/new", follow_redirects=False)
    pid = int(create.headers["location"].split("/")[2].split("?")[0])

    save = await client.post(
        f"/projects/{pid}",
        data={
            "name": "Voron Build",
            "description": "Full build journal",
            "status": "printing",
            "tags": "voron, build",
            "notes": "ordered the heatsets",
            "printer_id": "",
        },
        follow_redirects=False,
    )
    assert save.status_code == 303
    # Exits to read mode.
    assert save.headers["location"] == f"/projects/{pid}"

    api = await client.get(f"/api/projects/{pid}")
    body = api.json()
    assert body["name"] == "Voron Build"
    assert body["status"] == "printing"
    assert body["notes"] == "ordered the heatsets"
    assert body["tags"] == ["voron", "build"]


async def test_add_to_bom_stays_in_edit_mode(client: AsyncClient) -> None:
    """Non-HTMX BOM add (e.g. JS-disabled fallback) keeps the user in
    edit mode rather than kicking them out."""
    create = await client.post("/projects/new", follow_redirects=False)
    pid = int(create.headers["location"].split("/")[2].split("?")[0])

    resp = await client.post(
        f"/projects/{pid}/items",
        data={"name": "M3x12 SHCS", "qty_required": "5", "qty_consumed": "0"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/projects/{pid}?edit=true"


async def test_old_project_form_routes_are_gone(client: AsyncClient) -> None:
    assert (await client.get("/projects/new")).status_code in (404, 422)

    create = await client.post("/projects/new", follow_redirects=False)
    pid = int(create.headers["location"].split("/")[2].split("?")[0])
    assert (await client.get(f"/projects/{pid}/edit")).status_code == 404


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
