from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import PrinterFactory, persist


async def test_create_printer(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/printers",
        json={
            "name": "Voron 2.4 350",
            "model": "Voron 2.4 350mm",
            "access_url": "http://voron.local",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Voron 2.4 350"


async def test_list_printers(client: AsyncClient, session: AsyncSession) -> None:
    await persist(session, PrinterFactory(name="A"))
    await persist(session, PrinterFactory(name="B"))
    await session.commit()

    resp = await client.get("/api/printers")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_update_and_delete_printer(client: AsyncClient, session: AsyncSession) -> None:
    p = await persist(session, PrinterFactory())
    await session.commit()

    patch = await client.patch(f"/api/printers/{p.id}", json={"notes": "updated"})
    assert patch.status_code == 200
    assert patch.json()["notes"] == "updated"

    delete = await client.delete(f"/api/printers/{p.id}")
    assert delete.status_code == 204


async def test_empty_name_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/printers", json={"name": ""})
    assert resp.status_code == 422


async def test_printers_list_renders(client: AsyncClient, session: AsyncSession) -> None:
    await persist(session, PrinterFactory(name="Voron Bench"))
    await session.commit()

    resp = await client.get("/printers")
    assert resp.status_code == 200
    assert "Voron Bench" in resp.text


async def test_new_printer_button_creates_draft_and_redirects_to_edit(
    client: AsyncClient,
) -> None:
    """The list page's '+ New printer' button POSTs to /printers/new
    which creates a stub printer named 'New printer' and drops the user
    on the detail page in edit mode to fill in the rest."""
    resp = await client.post("/printers/new", follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/printers/")
    assert location.endswith("?edit=true")

    detail = await client.get(location)
    assert detail.status_code == 200
    # Edit mode renders the basic-fields form with the placeholder name
    # pre-filled in the input + the top-right action buttons.
    assert 'value="New printer"' in detail.text
    assert "Done editing" in detail.text
    assert "Delete printer" in detail.text


async def test_done_editing_saves_and_exits(client: AsyncClient) -> None:
    """Clicking Done editing (the submit button of the basic-fields
    form) saves the fields AND redirects out of edit mode."""
    create = await client.post("/printers/new", follow_redirects=False)
    pid = int(create.headers["location"].split("/")[2].split("?")[0])

    save = await client.post(
        f"/printers/{pid}",
        data={"name": "Voron 2.4", "model": "Voron 2.4 350", "access_url": "", "notes": ""},
        follow_redirects=False,
    )
    assert save.status_code == 303
    # Exits edit mode now.
    assert save.headers["location"] == f"/printers/{pid}"

    api = await client.get(f"/api/printers/{pid}")
    body = api.json()
    assert body["name"] == "Voron 2.4"
    assert body["model"] == "Voron 2.4 350"


async def test_inline_edit_validation_re_renders_in_edit_mode(client: AsyncClient) -> None:
    create = await client.post("/printers/new", follow_redirects=False)
    pid = int(create.headers["location"].split("/")[2].split("?")[0])

    # Empty name is required -> 400 with errors banner, still on detail page.
    bad = await client.post(f"/printers/{pid}", data={"name": ""}, follow_redirects=False)
    assert bad.status_code == 400
    # Edit affordances are still on the page so the user can fix and retry.
    assert "Done editing" in bad.text


async def test_done_editing_and_delete_buttons_wire_to_forms(client: AsyncClient) -> None:
    """Top-right action buttons in edit mode are submit buttons for the
    two hidden forms on the page — one for save, one for delete."""
    create = await client.post("/printers/new", follow_redirects=False)
    pid = int(create.headers["location"].split("/")[2].split("?")[0])

    edit = await client.get(f"/printers/{pid}?edit=true")
    assert 'form="printer-basic-form"' in edit.text
    assert 'form="printer-delete-form"' in edit.text
    # The forms exist with the matching ids.
    assert 'id="printer-basic-form"' in edit.text
    assert 'id="printer-delete-form"' in edit.text


async def test_delete_button_in_edit_mode_works(client: AsyncClient) -> None:
    create = await client.post("/printers/new", follow_redirects=False)
    pid = int(create.headers["location"].split("/")[2].split("?")[0])

    resp = await client.post(f"/printers/{pid}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/printers"

    gone = await client.get(f"/api/printers/{pid}")
    assert gone.status_code == 404


async def test_old_form_routes_are_gone(client: AsyncClient) -> None:
    """Standalone /printers/new GET and /printers/{id}/edit are dropped
    in favor of the consolidated detail page."""
    # GET /printers/new is no longer a route. With the {printer_id} catch-all
    # GET still in place, this resolves to the detail handler with an
    # invalid int and 422s — fine, the user-facing point is "not a page".
    assert (await client.get("/printers/new")).status_code in (404, 422)

    create = await client.post("/printers/new", follow_redirects=False)
    pid = int(create.headers["location"].split("/")[2].split("?")[0])
    assert (await client.get(f"/printers/{pid}/edit")).status_code == 404
