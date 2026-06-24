import io

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.schemas.project import ProjectItemLinkCreate
from maketrack.services import bom as bom_svc
from maketrack.services import project_links as link_svc
from maketrack.services import projects as project_svc
from tests.factories import (
    PrinterFactory,
    add_model_asset,
    link_item,
    link_model,
    make_inventory_item,
    make_model,
    make_project,
    persist,
)

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\x00"
    b"\x01\xfd\xc7\xa6X\xc0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _stl_bytes() -> bytes:
    return b"\x00" * 80 + (0).to_bytes(4, "little")


# ── unlinked custom BOM items ──────────────────────────────────────────────


async def test_add_custom_bom_item_without_inventory(session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id

    await link_item(session, pid, name="M3x12 SHCS", unit="each", qty_required=20)

    items = await link_svc.list_project_items(session, pid)
    assert len(items) == 1
    h = items[0]
    assert h.link.inventory_item_id is None
    assert h.link.name == "M3x12 SHCS"
    assert h.display_name == "M3x12 SHCS"


async def test_bom_unlinked_row_has_null_on_hand_and_full_still_to_buy(
    session: AsyncSession,
) -> None:
    pid = (await make_project(session, name="P")).id
    await link_item(session, pid, name="Mystery Bolt", qty_required=50, qty_consumed=10)

    bom = await bom_svc.project_bom(session, pid)
    assert len(bom) == 1
    row = bom[0]
    assert row.inventory_item_id is None
    assert row.on_hand is None
    assert row.still_needed_for_project == 40
    assert row.still_to_buy == 40


async def test_add_bom_with_neither_id_nor_name_fails(session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    with pytest.raises(ValueError):
        await link_svc.add_item(session, pid, ProjectItemLinkCreate(qty_required=5))


async def test_late_link_inventory_to_custom_bom(session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    item = await make_inventory_item(session, name="M3x12 SHCS", quantity=5)
    custom = await link_item(session, pid, name="M3x12 SHCS", qty_required=10)

    linked = await link_svc.link_item_to_inventory(session, custom.id, item.id)
    await session.commit()
    assert linked.inventory_item_id == item.id
    # Original typed name is preserved on the link as a record.
    assert linked.name == "M3x12 SHCS"

    # BOM row now reflects on_hand from the linked inventory.
    bom = await bom_svc.project_bom(session, pid)
    assert bom[0].on_hand == 5
    assert bom[0].still_to_buy == 5


async def test_shopping_list_includes_unlinked_rows(session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    await link_item(session, pid, name="Mystery Hardware", qty_required=12)

    rows = await bom_svc.shopping_list(session)
    names = [r.name for r in rows]
    assert "Mystery Hardware" in names
    mystery = next(r for r in rows if r.name == "Mystery Hardware")
    assert mystery.inventory_item_id is None
    assert mystery.still_to_buy == 12


# ── project file upload removed ─────────────────────────────────────────────
# Models are created/grouped only in the Models section now; the project page
# links existing files via the picker rather than auto-creating one model per
# dropped file. The old POST /projects/{id}/upload-files route is gone.


async def test_project_upload_files_route_is_gone(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = (await make_project(session, name="P")).id
    resp = await client.post(
        f"/projects/{pid}/upload-files",
        files=[("files", ("bracket.stl", io.BytesIO(_stl_bytes()), "model/stl"))],
        follow_redirects=False,
    )
    assert resp.status_code in (404, 405)


# ── project photos ─────────────────────────────────────────────────────────


async def test_upload_cover_photo(client: AsyncClient, session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id

    resp = await client.post(
        f"/projects/{pid}/photo/cover",
        files={"file": ("cover.png", io.BytesIO(_PNG), "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    detail = await client.get(f"/projects/{pid}")
    # The detail page renders <img src="/media/projects/<uuid>.png"> for the cover.
    assert "/media/projects/" in detail.text


async def test_upload_completed_photo_separate_slot(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = (await make_project(session, name="P")).id

    await client.post(
        f"/projects/{pid}/photo/cover",
        files={"file": ("c.png", io.BytesIO(_PNG), "image/png")},
        follow_redirects=False,
    )
    await client.post(
        f"/projects/{pid}/photo/completed",
        files={"file": ("a.png", io.BytesIO(_PNG), "image/png")},
        follow_redirects=False,
    )
    import re

    detail = await client.get(f"/projects/{pid}")
    paths = re.findall(r"/media/projects/[a-f0-9]+\.png", detail.text)
    # Two distinct paths now persisted (cover + after).
    assert len(set(paths)) >= 2


async def test_replace_photo_drops_old_file(client: AsyncClient, session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id

    await client.post(
        f"/projects/{pid}/photo/cover",
        files={"file": ("first.png", io.BytesIO(_PNG), "image/png")},
        follow_redirects=False,
    )
    detail1 = await client.get(f"/projects/{pid}")
    import re

    first = re.search(r"/media/projects/[a-f0-9]+\.png", detail1.text).group(0)

    await client.post(
        f"/projects/{pid}/photo/cover",
        files={"file": ("second.png", io.BytesIO(_PNG), "image/png")},
        follow_redirects=False,
    )

    # The old file should be gone from disk.
    gone = await client.get(first)
    assert gone.status_code == 404


async def test_unknown_photo_kind_is_a_noop(client: AsyncClient, session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    resp = await client.post(
        f"/projects/{pid}/photo/sideways",
        files={"file": ("a.png", io.BytesIO(_PNG), "image/png")},
        follow_redirects=False,
    )
    # Redirects without persisting (unknown slot is rejected silently).
    assert resp.status_code == 303


# ── M6 polish: cover photo on list, inline qty, inline notes ──────────────


async def test_project_list_renders_cover_photo(client: AsyncClient, session: AsyncSession) -> None:
    pid = (await make_project(session, name="Cover Test")).id
    await client.post(
        f"/projects/{pid}/photo/cover",
        files={"file": ("c.png", io.BytesIO(_PNG), "image/png")},
        follow_redirects=False,
    )

    resp = await client.get("/projects")
    assert resp.status_code == 200
    import re

    match = re.search(r"/media/projects/[a-f0-9]+\.png", resp.text)
    assert match, "cover photo URL not found in /projects page"


async def test_inline_qty_required_save(client: AsyncClient, session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    item = await make_inventory_item(session, name="Bolt", quantity=0)
    link = await link_item(session, pid, inventory_item_id=item.id, qty_required=10)

    resp = await client.post(
        f"/projects/{pid}/items/{link.id}/qty",
        data={"qty_required": "25"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    session.expire_all()
    bom = await bom_svc.project_bom(session, pid)
    assert bom[0].still_needed_for_project == 25


async def test_inline_qty_consumed_save(client: AsyncClient, session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    item = await make_inventory_item(session, name="Bolt", quantity=100)
    link = await link_item(session, pid, inventory_item_id=item.id, qty_required=10)

    await client.post(
        f"/projects/{pid}/items/{link.id}/qty",
        data={"qty_consumed": "4"},
        follow_redirects=False,
    )
    session.expire_all()
    bom = await bom_svc.project_bom(session, pid)
    assert bom[0].still_needed_for_project == 6  # 10 - 4


async def test_inline_qty_invalid_input_is_ignored(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = (await make_project(session, name="P")).id
    item = await make_inventory_item(session, name="Bolt")
    link = await link_item(session, pid, inventory_item_id=item.id, qty_required=10)

    resp = await client.post(
        f"/projects/{pid}/items/{link.id}/qty",
        data={"qty_required": "not-a-number"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    session.expire_all()
    bom = await bom_svc.project_bom(session, pid)
    assert bom[0].still_needed_for_project == 10  # unchanged


async def test_notes_save_via_basic_fields_form(client: AsyncClient, session: AsyncSession) -> None:
    """Notes are saved as part of the basic-fields form on the detail
    page (clicking Done editing); the standalone /notes endpoint is
    gone in favor of one consolidated save."""
    pid = (await make_project(session, name="P")).id

    resp = await client.post(
        f"/projects/{pid}",
        data={"name": "P", "notes": "ordered the heatsets, ETA Friday"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    session.expire_all()
    fetched = await project_svc.get_project(session, pid)
    assert fetched.notes == "ordered the heatsets, ETA Friday"


async def test_notes_clears_on_empty_via_basic_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = (await make_project(session, name="P", notes="first pass")).id

    await client.post(
        f"/projects/{pid}",
        data={"name": "P", "notes": ""},
        follow_redirects=False,
    )
    session.expire_all()
    fetched = await project_svc.get_project(session, pid)
    assert fetched.notes is None


async def test_edit_form_clears_description(client: AsyncClient, session: AsyncSession) -> None:
    """Regression: clearing description in the edit form must persist as
    NULL, not silently keep the old text. The bug was that
    strip_empty_strings dropped empty keys from the PATCH payload, which
    Pydantic's exclude_unset interpreted as "no change."
    """
    pid = (await make_project(session, name="Has Desc", description="first pass")).id

    # Use the form-based edit POST to "save" with description cleared.
    resp = await client.post(
        f"/projects/{pid}",
        data={"name": "Has Desc", "description": "", "status": "planning"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    session.expire_all()
    fetched = await project_svc.get_project(session, pid)
    assert fetched.description is None


async def test_edit_mode_renders_notes_textarea(client: AsyncClient, session: AsyncSession) -> None:
    """Notes lives inside the basic-fields form on the detail page in
    edit mode — it commits with everything else on Done editing."""
    pid = (await make_project(session, name="P")).id
    edit = await client.get(f"/projects/{pid}?edit=true")
    assert edit.status_code == 200
    assert 'name="notes"' in edit.text


async def test_qty_edit_returns_partial_for_htmx(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Regression: BOM qty edits must return JUST the BOM section partial
    when the request comes from HTMX, so the rest of the page (and the
    user's scroll position) doesn't get blown away."""
    pid = (await make_project(session, name="P")).id
    item = await make_inventory_item(session, name="Bolt")
    link = await link_item(session, pid, inventory_item_id=item.id, qty_required=10)

    resp = await client.post(
        f"/projects/{pid}/items/{link.id}/qty",
        data={"qty_required": "25"},
        headers={"HX-Request": "true"},
    )
    # HTMX swap responses are 200 with HTML, not 303 redirects.
    assert resp.status_code == 200
    assert 'id="bom-section"' in resp.text
    # And the new value rendered into the partial.
    assert "25" in resp.text
    # Confirm we got JUST the section, not the full page.
    assert "<html" not in resp.text.lower()


async def test_qty_edit_redirects_for_non_htmx(client: AsyncClient, session: AsyncSession) -> None:
    """Non-HTMX clients (curl, plain HTML form fallback) still get the
    303 redirect so they can resume normal page navigation."""
    pid = (await make_project(session, name="P")).id
    item = await make_inventory_item(session, name="Bolt")
    link = await link_item(session, pid, inventory_item_id=item.id, qty_required=10)

    resp = await client.post(
        f"/projects/{pid}/items/{link.id}/qty",
        data={"qty_required": "25"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


async def test_add_bom_via_htmx_returns_section_with_new_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = (await make_project(session, name="P")).id

    resp = await client.post(
        f"/projects/{pid}/items",
        data={"name": "M3x12 SHCS", "qty_required": "5", "qty_consumed": "0"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert 'id="bom-section"' in resp.text
    assert "M3x12 SHCS" in resp.text
    # The empty entry row should still be at the bottom (input by id).
    assert 'id="bom-entry-name"' in resp.text


async def test_empty_bom_submit_via_htmx_is_a_noop(
    client: AsyncClient, session: AsyncSession
) -> None:
    """User tabs through the entry row without typing — should not create
    a row, just re-render the partial."""
    pid = (await make_project(session, name="P")).id

    resp = await client.post(
        f"/projects/{pid}/items",
        data={"name": "", "qty_required": "1", "qty_consumed": "0", "inventory_item_id": ""},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert await link_svc.list_project_items(session, pid) == []


async def test_model_qty_to_print_inline_edit(client: AsyncClient, session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="Bracket")).id
    aid = await add_model_asset(session, mid)
    await link_model(session, pid, aid, qty_to_print=1)

    resp = await client.post(
        f"/projects/{pid}/models/{aid}/qty",
        data={"qty_to_print": "12"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert 'id="models-section"' in resp.text

    session.expire_all()
    rows = await link_svc.list_project_models(session, pid)
    assert rows[0].link.qty_to_print == 12


async def test_model_qty_rejects_below_one(client: AsyncClient, session: AsyncSession) -> None:
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="M")).id
    aid = await add_model_asset(session, mid)
    await link_model(session, pid, aid, qty_to_print=3)

    await client.post(
        f"/projects/{pid}/models/{aid}/qty",
        data={"qty_to_print": "0"},
        headers={"HX-Request": "true"},
    )
    session.expire_all()
    rows = await link_svc.list_project_models(session, pid)
    assert rows[0].link.qty_to_print == 3  # unchanged


async def test_detail_page_uses_tabbed_thumbnail_and_lightbox(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The detail page header should render the Alpine-tabbed thumbnail and
    a lightbox container; the per-photo upload forms moved to the edit
    page so they should NOT appear on detail."""
    pid = (await make_project(session, name="Tabbed")).id

    detail = await client.get(f"/projects/{pid}")
    assert detail.status_code == 200
    # Tab buttons exist (Alpine click handlers identify them).
    assert "tab = 'cover'" in detail.text
    assert "tab = 'completed'" in detail.text
    # Lightbox container is in the markup.
    assert "open-lightbox" in detail.text
    # No upload forms on the detail page anymore.
    assert f'/projects/{pid}/photo/cover"' not in detail.text
    assert f'/projects/{pid}/photo/completed"' not in detail.text


async def test_edit_mode_owns_photo_upload(client: AsyncClient, session: AsyncSession) -> None:
    """Photos upload forms now live inline on the detail page but only
    appear in edit mode (?edit=true)."""
    pid = (await make_project(session, name="Tabbed")).id
    edit = await client.get(f"/projects/{pid}?edit=true")
    assert edit.status_code == 200
    assert f'action="/projects/{pid}/photo/cover"' in edit.text
    assert f'action="/projects/{pid}/photo/completed"' in edit.text


async def test_description_renders_in_header_block_not_in_separate_card(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Description moved up next to the title (per UX feedback). The
    standalone Description card should be gone — there's only one place
    it can live now."""
    pid = (await make_project(session, name="P", description="first pass")).id
    detail = await client.get(f"/projects/{pid}")
    assert detail.status_code == 200
    assert "first pass" in detail.text
    # The old "Description" header section is gone — there should be at most
    # one "Description" string anywhere on the page (and ideally zero).
    assert detail.text.count(">Description<") == 0


async def test_printer_renders_on_status_row(client: AsyncClient, session: AsyncSession) -> None:
    """Printer info moved from below the title into the status row."""
    printer = await persist(session, PrinterFactory(name="Voron 2.4", model="Voron 2.4 350"))
    await session.commit()
    pid = (await make_project(session, name="P", printer_id=printer.id)).id

    detail = await client.get(f"/projects/{pid}")
    # The printer name should appear once on the page, inside the status row.
    assert "Voron 2.4" in detail.text


async def test_model_link_status_select_renders_in_edit_mode(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="Bracket")).id
    aid = await add_model_asset(session, mid)
    await link_model(session, pid, aid)

    # The inline status select is an edit affordance; gated behind ?edit=true.
    detail = await client.get(f"/projects/{pid}?edit=true")
    assert f"/projects/{pid}/models/{aid}/status" in detail.text


async def test_model_link_status_chip_in_read_mode(
    client: AsyncClient, session: AsyncSession
) -> None:
    """In read mode the model link's status renders as a static chip
    instead of an editable select."""
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="Bracket")).id
    aid = await add_model_asset(session, mid)
    await link_model(session, pid, aid)

    detail = await client.get(f"/projects/{pid}")
    # The editable select is hidden in read mode.
    assert f"/projects/{pid}/models/{aid}/status" not in detail.text
    # Status chip still shows the value.
    assert ">pending<" in detail.text


async def test_model_status_inline_edit_persists(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="Bracket")).id
    aid = await add_model_asset(session, mid)
    await link_model(session, pid, aid)

    resp = await client.post(
        f"/projects/{pid}/models/{aid}/status",
        data={"status": "printed"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert 'id="models-section"' in resp.text

    session.expire_all()
    rows = await link_svc.list_project_models(session, pid)
    assert rows[0].link.status == "printed"


async def test_model_status_rejects_invalid_value(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Anything outside the pending|printed|failed set is silently ignored
    so the row doesn't end up in a stuck/illegal state."""
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="M")).id
    aid = await add_model_asset(session, mid)
    await link_model(session, pid, aid)

    await client.post(
        f"/projects/{pid}/models/{aid}/status",
        data={"status": "shipped"},
        headers={"HX-Request": "true"},
    )
    session.expire_all()
    rows = await link_svc.list_project_models(session, pid)
    # Status untouched — still pending (the default).
    assert rows[0].link.status == "pending"


async def test_edit_mode_renders_inline_widgets(client: AsyncClient, session: AsyncSession) -> None:
    """In edit mode the detail page shows qty inputs (HTMX-wired) and
    the notes textarea inside the basic-fields form."""
    pid = (await make_project(session, name="Widgets")).id
    item = await make_inventory_item(session, name="Bolt")
    await link_item(session, pid, inventory_item_id=item.id, qty_required=5)

    detail = await client.get(f"/projects/{pid}?edit=true")
    assert detail.status_code == 200
    # Inline qty form posts to the qty endpoint per row.
    assert f"/projects/{pid}/items/" in detail.text
    assert "/qty" in detail.text
    # Notes textarea is part of the basic-fields form.
    assert 'name="notes"' in detail.text


async def test_model_picker_renders_collapsible_browser(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The 'link a model' UI is an in-page collapsible browser (collection
    name → its files with a per-file Link button), not a flat dropdown that
    lists every file across every collection."""
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="Voron Skirt")).id
    aid = await add_model_asset(session, mid, "skirt.stl")

    detail = await client.get(f"/projects/{pid}?edit=true")
    body = detail.text
    # Collection name + filename are shown, each file gets a Link button that
    # POSTs the asset id to the add-model endpoint.
    assert "Voron Skirt" in body
    assert "skirt.stl" in body
    assert f'hx-post="/projects/{pid}/models"' in body
    assert f'"model_asset_id": "{aid}"' in body
    # The library filter input is present; the old flat <optgroup> select is gone.
    assert 'placeholder="Filter collections' in body
    assert "<optgroup" not in body


async def test_model_picker_excludes_images(client: AsyncClient, session: AsyncSession) -> None:
    """You link a printable file to a project, not a thumbnail — image assets
    don't appear in the picker, and a collection with only images is omitted."""
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="PhotoOnly")).id
    # Upload only an image (becomes the thumbnail) — no printable file.
    await add_model_asset(session, mid, "cover.png", data=_PNG)

    detail = await client.get(f"/projects/{pid}?edit=true")
    assert "cover.png" not in detail.text
    # No printable file anywhere → the empty-state copy shows instead.
    assert "already linked" in detail.text


async def test_model_picker_hides_already_linked_file(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Once a file is linked it drops out of the browser (only unlinked,
    printable files are offered)."""
    pid = (await make_project(session, name="P")).id
    mid = (await make_model(session, name="Bracket")).id
    aid = await add_model_asset(session, mid, "bracket.stl")
    await link_model(session, pid, aid)

    detail = await client.get(f"/projects/{pid}?edit=true")
    # The linked file shows in the linked list but not as a picker Link button.
    assert f'"model_asset_id": "{aid}"' not in detail.text
    assert "already linked" in detail.text
