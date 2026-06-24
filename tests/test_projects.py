import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.schemas.project import ProjectCreate
from maketrack.services import project_links as link_svc
from maketrack.services import projects as project_svc
from tests.factories import (
    InventoryItemFactory,
    LocalFilamentFactory,
    PrinterFactory,
    add_model_asset,
    link_filament,
    link_item,
    link_model,
    make_model,
    make_project,
    persist,
    update_project,
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


async def test_project_detail_read_mode_hides_edit_affordances(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = (await make_project(session, name="P")).id

    read = await client.get(f"/projects/{pid}")
    # No basic-field inputs in read mode.
    assert 'name="name"' not in read.text
    # Edit toggle entry.
    assert "Edit page" in read.text


async def test_project_detail_edit_mode_reveals_form(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = (await make_project(session, name="Editable")).id

    edit = await client.get(f"/projects/{pid}?edit=true")
    assert 'value="Editable"' in edit.text
    assert "Done editing" in edit.text
    # Photos upload forms appear in edit mode.
    assert f'action="/projects/{pid}/photo/cover"' in edit.text


async def test_done_editing_saves_and_exits_read_mode(
    client: AsyncClient, session: AsyncSession
) -> None:
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

    saved = await project_svc.get_project(session, pid)
    assert saved.name == "Voron Build"
    assert saved.status == "printing"
    assert saved.notes == "ordered the heatsets"
    assert project_svc.decode_tags(saved.tags) == ["voron", "build"]


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


# ── service-level project behavior ────────────────────────────────────────


async def test_create_project_minimal(session: AsyncSession) -> None:
    project = await make_project(session, name="Voron 2.4 Build", tags=["voron", "build"])
    assert project.name == "Voron 2.4 Build"
    assert project.status == "planning"
    assert project_svc.decode_tags(project.tags) == ["voron", "build"]
    assert project.completed_at is None


async def test_status_done_stamps_completed_at(session: AsyncSession) -> None:
    project = await make_project(session, name="P")
    updated = await update_project(session, project.id, status="done")
    assert updated.status == "done"
    assert updated.completed_at is not None


async def test_status_back_to_planning_clears_completed_at(session: AsyncSession) -> None:
    project = await make_project(session, name="P")
    await update_project(session, project.id, status="done")
    updated = await update_project(session, project.id, status="planning")
    assert updated.completed_at is None


async def test_invalid_status_rejected() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="P", status="shipped")


async def test_list_filter_by_status(session: AsyncSession) -> None:
    a = await make_project(session, name="Active")
    await update_project(session, a.id, status="printing")
    await make_project(session, name="Idle")

    rows = await project_svc.list_projects(session, status="printing")
    assert [p.name for p in rows] == ["Active"]


async def test_link_printer(session: AsyncSession) -> None:
    p = await persist(session, PrinterFactory(name="Voron"))
    await session.commit()

    project = await make_project(session, name="P", printer_id=p.id)
    assert project.printer_id == p.id


async def test_add_model_link_idempotent(session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="M")).id
    aid = await add_model_asset(session, mid)

    await link_model(session, pid, aid, qty_to_print=2)
    # Re-link with different qty — should not violate the composite PK; the
    # service treats it as an upsert.
    await link_model(session, pid, aid, qty_to_print=5)

    links = await link_svc.list_project_models(session, pid)
    assert len(links) == 1
    assert links[0].link.qty_to_print == 5


async def test_remove_model_link(session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="M")).id
    aid = await add_model_asset(session, mid)
    await link_model(session, pid, aid)

    await link_svc.remove_model(session, pid, aid)
    await session.commit()
    assert await link_svc.list_project_models(session, pid) == []


async def test_filament_link_round_trip(session: AsyncSession) -> None:
    f = await persist(session, LocalFilamentFactory(name="PLA Black"))
    await session.commit()
    pid = (await make_project(session, name="P")).id

    link = await link_filament(session, pid, f.id, est_weight_g=250, role="extruder_0")

    links = await link_svc.list_project_filaments(session, pid)
    assert len(links) == 1
    assert links[0].link.role == "extruder_0"

    await link_svc.remove_filament(session, link.id)
    await session.commit()
    assert await link_svc.list_project_filaments(session, pid) == []


async def test_item_link_decimal_qty(session: AsyncSession) -> None:
    item = await persist(session, InventoryItemFactory(name="XT60 wire", quantity=2, unit="m"))
    await session.commit()
    pid = (await make_project(session, name="P")).id

    link = await link_item(session, pid, inventory_item_id=item.id, qty_required=1.5)
    assert link.qty_required == 1.5
