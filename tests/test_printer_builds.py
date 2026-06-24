"""Printer detail page, photo, and the per-printer build list — each
build can link to a project and to many models with qty + notes."""

import io

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.schemas.printer import (
    PrinterBuildCreate,
    PrinterBuildModelCreate,
    PrinterBuildRead,
    PrinterCreate,
)
from maketrack.services import printer_builds as build_svc
from maketrack.services import printers as printer_svc
from maketrack.services import projects as project_svc
from tests.factories import make_model, make_project

# 1x1 PNG so the multipart upload path actually exercises save_photo.
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\x00"
    b"\x01\xfd\xc7\xa6X\xc0\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _new_printer(session: AsyncSession, name: str = "Voron 0") -> int:
    p = await printer_svc.create_printer(session, PrinterCreate(name=name, model="Voron 0.2"))
    await session.commit()
    return p.id


async def _new_model(session: AsyncSession, name: str) -> int:
    return (await make_model(session, name=name)).id


async def _new_project(session: AsyncSession, name: str) -> int:
    return (await make_project(session, name=name)).id


async def _make_build(session: AsyncSession, printer_id: int, **kw) -> int:
    build = await build_svc.create_build(
        session, printer_id=printer_id, payload=PrinterBuildCreate(**{"name": "x", **kw})
    )
    await session.commit()
    return build.id


async def _link_model(session: AsyncSession, build_id: int, model_id: int, qty: int = 1, notes=None):
    link = await build_svc.add_model(
        session,
        build_id=build_id,
        payload=PrinterBuildModelCreate(model_id=model_id, qty=qty, notes=notes),
    )
    await session.commit()
    return link


async def _read_build(session: AsyncSession, build_id: int) -> PrinterBuildRead:
    # Fresh DB state so cascade / SET NULL effects are visible.
    session.expire_all()
    return PrinterBuildRead.model_validate(await build_svc.get_build(session, build_id))


async def _list_builds(session: AsyncSession, printer_id: int) -> list[PrinterBuildRead]:
    session.expire_all()
    builds = await build_svc.list_for_printer(session, printer_id)
    return [PrinterBuildRead.model_validate(b) for b in builds]


async def test_detail_read_mode_hides_edit_affordances(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Default page is reading-style: no add forms, no upload form."""
    pid = await _new_printer(session)
    resp = await client.get(f"/printers/{pid}")
    assert resp.status_code == 200
    assert "Voron 0" in resp.text
    assert "Build" in resp.text
    # Edit toggle is the entry point.
    assert "?edit=true" in resp.text
    # Add forms are NOT rendered in read mode.
    assert ">Add model<" not in resp.text
    assert ">Add project<" not in resp.text
    assert ">Add custom<" not in resp.text
    # Upload form for an absent photo is NOT rendered in read mode.
    assert "No photo yet" not in resp.text


async def test_detail_edit_mode_reveals_forms(client: AsyncClient, session: AsyncSession) -> None:
    pid = await _new_printer(session)
    resp = await client.get(f"/printers/{pid}?edit=true")
    assert resp.status_code == 200
    # All three add paths show in edit mode.
    assert ">Add model<" in resp.text
    assert ">Add project<" in resp.text
    assert ">Add custom<" in resp.text
    # Top-right action buttons in edit mode.
    assert ">Done editing<" in resp.text
    assert ">Delete printer<" in resp.text
    # Upload form for an absent photo IS rendered in edit mode.
    assert "No photo yet" in resp.text


async def test_edit_page_button_active_state(client: AsyncClient, session: AsyncSession) -> None:
    """The Edit page link is an outline link in read mode; on the edit
    layout it's replaced by a solid emerald 'Done editing' submit
    button — visual signal that you're currently editing."""
    pid = await _new_printer(session)

    read = await client.get(f"/printers/{pid}")
    assert ">Edit page<" in read.text
    # Outline (border + slate text) on the toggle in read mode.
    assert "border-slate-300" in read.text
    # No "Done editing" label in read mode.
    assert "Done editing" not in read.text

    edit = await client.get(f"/printers/{pid}?edit=true")
    # Done editing is now the submit button of the basic-fields form,
    # styled with the active emerald background.
    import re

    match = re.search(
        r'<button[^>]+form="printer-basic-form"[^>]+class="[^"]*bg-crimson[^"]*"[^>]*>\s*Done editing\s*</button>',
        edit.text,
    )
    assert match, "Done editing should be the active crimson submit button"


async def test_printer_photo_upload_and_remove(client: AsyncClient, session: AsyncSession) -> None:
    pid = await _new_printer(session)

    upload = await client.post(
        f"/printers/{pid}/photo",
        files={"photo": ("p.png", io.BytesIO(_PNG_1X1), "image/png")},
        follow_redirects=False,
    )
    assert upload.status_code == 303

    detail = await client.get(f"/printers/{pid}")
    assert "/media/printers/" in detail.text

    # Remove resets photo_path; the detail page falls back to the upload form.
    removed = await client.post(f"/printers/{pid}/photo/delete", follow_redirects=False)
    assert removed.status_code == 303

    detail = await client.get(f"/printers/{pid}")
    assert "/media/printers/" not in detail.text


async def test_create_build(client: AsyncClient, session: AsyncSession) -> None:
    pid = await _new_printer(session)
    proj_id = await _new_project(session, "Voron 0.2 build journal")

    build_id = await _make_build(
        session, pid, name="PEI bed", source_project_id=proj_id, description="smooth"
    )
    body = await _read_build(session, build_id)
    assert body.name == "PEI bed"
    assert body.source_project.id == proj_id
    assert body.source_project.name == "Voron 0.2 build journal"
    assert body.model_links == []


async def test_link_and_unlink_models(client: AsyncClient, session: AsyncSession) -> None:
    pid = await _new_printer(session)
    duct_id = await _new_model(session, "Stealthburner duct")
    fan_id = await _new_model(session, "5015 fan mount")

    build_id = await _make_build(session, pid, name="Cooling upgrade")

    await _link_model(session, build_id, duct_id, qty=1, notes="front")
    await _link_model(session, build_id, fan_id, qty=2)

    full = await _read_build(session, build_id)
    links = {link.model_id: link for link in full.model_links}
    assert set(links) == {duct_id, fan_id}
    assert links[duct_id].qty == 1
    assert links[duct_id].notes == "front"
    assert links[duct_id].model.name == "Stealthburner duct"
    assert links[fan_id].qty == 2

    await build_svc.remove_model(session, build_id=build_id, model_id=fan_id)
    await session.commit()

    full = await _read_build(session, build_id)
    assert [link.model_id for link in full.model_links] == [duct_id]


async def test_link_unknown_model_404s(client: AsyncClient, session: AsyncSession) -> None:
    pid = await _new_printer(session)
    build_id = await _make_build(session, pid, name="x")

    with pytest.raises(NotFoundError):
        await build_svc.add_model(
            session, build_id=build_id, payload=PrinterBuildModelCreate(model_id=99999, qty=1)
        )


async def test_qty_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        PrinterBuildModelCreate(model_id=1, qty=0)


async def test_ui_add_model_path_seeds_name_and_link(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Picking a model from the inline form creates a build named after
    the model AND auto-links the model — no name typing required."""
    pid = await _new_printer(session)
    mid = await _new_model(session, "Stealthburner duct")

    create = await client.post(
        f"/printers/{pid}/builds",
        data={"model_id": str(mid)},
        follow_redirects=False,
    )
    assert create.status_code == 303

    builds = await _list_builds(session, pid)
    assert len(builds) == 1
    assert builds[0].name == "Stealthburner duct"
    links = builds[0].model_links
    assert len(links) == 1
    assert links[0].model_id == mid
    assert links[0].qty == 1


async def test_ui_add_project_path_uses_project_name(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Picking a project doesn't require typing a build name — the
    project's own name is used."""
    pid = await _new_printer(session)
    proj_id = await _new_project(session, "Skirts journal")

    create = await client.post(
        f"/printers/{pid}/builds",
        data={"source_project_id": str(proj_id)},
        follow_redirects=False,
    )
    assert create.status_code == 303

    builds = await _list_builds(session, pid)
    assert len(builds) == 1
    assert builds[0].name == "Skirts journal"
    assert builds[0].source_project.id == proj_id
    assert builds[0].model_links == []

    detail = await client.get(f"/printers/{pid}")
    assert f'href="/projects/{proj_id}"' in detail.text


async def test_ui_add_custom_name_path(client: AsyncClient, session: AsyncSession) -> None:
    """Custom name path: just text, no model or project — for things
    like 'Custom wiring' that don't link to either."""
    pid = await _new_printer(session)

    create = await client.post(
        f"/printers/{pid}/builds",
        data={"name": "Custom wiring"},
        follow_redirects=False,
    )
    assert create.status_code == 303

    builds = await _list_builds(session, pid)
    assert len(builds) == 1
    assert builds[0].name == "Custom wiring"
    assert builds[0].source_project is None
    assert builds[0].model_links == []


async def test_card_for_model_entry_links_to_model(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A build entry created from a model becomes a clickable card whose
    primary target is that model — even in read mode."""
    pid = await _new_printer(session)
    mid = await _new_model(session, "duct")
    await client.post(
        f"/printers/{pid}/builds",
        data={"model_id": str(mid)},
        follow_redirects=False,
    )

    detail = await client.get(f"/printers/{pid}")
    # Stretched-link wrapper carries the navigation target.
    assert f'href="/models/{mid}"' in detail.text


async def test_card_for_project_entry_links_to_project(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = await _new_printer(session)
    proj_id = await _new_project(session, "Skirts journal")
    await client.post(
        f"/printers/{pid}/builds",
        data={"source_project_id": str(proj_id)},
        follow_redirects=False,
    )

    detail = await client.get(f"/printers/{pid}")
    assert f'href="/projects/{proj_id}"' in detail.text


async def test_card_for_custom_entry_has_no_link(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A custom-name entry with no model and no project doesn't link
    anywhere — it's read-only text on the detail page."""
    pid = await _new_printer(session)
    await client.post(
        f"/printers/{pid}/builds",
        data={"name": "Custom wiring"},
        follow_redirects=False,
    )

    detail = await client.get(f"/printers/{pid}")
    assert "Custom wiring" in detail.text
    # No /models/N or /projects/N link in the card area; the only links
    # outside the card region are the printer nav, edit-details, edit-page.
    assert "/models/" not in detail.text
    assert "/projects/" not in detail.text


async def test_edit_buttons_only_render_in_edit_mode(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = await _new_printer(session)
    await client.post(
        f"/printers/{pid}/builds",
        data={"name": "Custom wiring"},
        follow_redirects=False,
    )

    read = await client.get(f"/printers/{pid}")
    assert "/builds/1/edit" not in read.text
    assert "/builds/1/delete" not in read.text

    edit = await client.get(f"/printers/{pid}?edit=true")
    assert "/builds/1/edit" in edit.text
    assert "/builds/1/delete" in edit.text


async def test_ui_link_more_models_via_edit_page(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Once a build exists (created from any path), the edit page lets
    you keep adding models with qty + notes."""
    pid = await _new_printer(session)
    mid = await _new_model(session, "skirt panel")

    create = await client.post(
        f"/printers/{pid}/builds",
        data={"name": "Skirts"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    build_id = (await _list_builds(session, pid))[0].id

    link = await client.post(
        f"/printers/{pid}/builds/{build_id}/models",
        data={"model_id": str(mid), "qty": "4", "notes": "corners"},
        follow_redirects=False,
    )
    assert link.status_code == 303

    detail = await client.get(f"/printers/{pid}")
    assert "skirt panel" in detail.text
    # Template renders qty as U+00D7 + digit.
    assert "×4" in detail.text


async def test_ui_empty_form_is_a_noop(client: AsyncClient, session: AsyncSession) -> None:
    """Submitting all three forms blank does nothing rather than 422'ing."""
    pid = await _new_printer(session)

    resp = await client.post(f"/printers/{pid}/builds", data={}, follow_redirects=False)
    assert resp.status_code == 303

    assert await _list_builds(session, pid) == []


async def test_ui_build_photo_upload_and_remove(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = await _new_printer(session)
    create = await client.post(
        f"/printers/{pid}/builds",
        data={"name": "Cover plate"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    build_id = (await _list_builds(session, pid))[0].id

    upload = await client.post(
        f"/printers/{pid}/builds/{build_id}",
        data={"name": "Cover plate"},
        files={"photo": ("p.png", io.BytesIO(_PNG_1X1), "image/png")},
        follow_redirects=False,
    )
    assert upload.status_code == 303

    detail = await client.get(f"/printers/{pid}")
    assert "/media/printers/builds/" in detail.text

    # Remove via the checkbox on update.
    removed = await client.post(
        f"/printers/{pid}/builds/{build_id}",
        data={"name": "Cover plate", "remove_photo": "true"},
        follow_redirects=False,
    )
    assert removed.status_code == 303

    detail = await client.get(f"/printers/{pid}")
    assert "/media/printers/builds/" not in detail.text


async def test_delete_build_stays_in_edit_mode(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = await _new_printer(session)
    build_id = await _make_build(session, pid, name="x")

    resp = await client.post(f"/printers/{pid}/builds/{build_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    # Stay in edit mode — user is still building out the printer.
    assert resp.headers["location"] == f"/printers/{pid}?edit=true"

    assert await _list_builds(session, pid) == []


async def test_add_to_build_actions_stay_in_edit_mode(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The three add-to-build paths return the user to edit mode so they
    can keep adding things without re-toggling. Only "Done editing" exits."""
    pid = await _new_printer(session)
    mid = await _new_model(session, "thing")
    proj_id = await _new_project(session, "j")

    for data in (
        {"model_id": str(mid)},
        {"source_project_id": str(proj_id)},
        {"name": "Custom"},
    ):
        resp = await client.post(f"/printers/{pid}/builds", data=data, follow_redirects=False)
        assert resp.status_code == 303, f"failed for {data!r}"
        assert resp.headers["location"] == f"/printers/{pid}?edit=true", (
            f"add path {data!r} kicked out of edit mode"
        )


async def test_photo_upload_and_remove_stay_in_edit_mode(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = await _new_printer(session)

    upload = await client.post(
        f"/printers/{pid}/photo",
        files={"photo": ("p.png", io.BytesIO(_PNG_1X1), "image/png")},
        follow_redirects=False,
    )
    assert upload.status_code == 303
    assert upload.headers["location"] == f"/printers/{pid}?edit=true"

    remove = await client.post(f"/printers/{pid}/photo/delete", follow_redirects=False)
    assert remove.status_code == 303
    assert remove.headers["location"] == f"/printers/{pid}?edit=true"


async def test_deleting_printer_cascades_builds(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = await _new_printer(session)
    mid = await _new_model(session, "duct")
    build_id = await _make_build(session, pid, name="x")
    await _link_model(session, build_id, mid, qty=1)

    await printer_svc.delete_printer(session, pid)
    await session.commit()

    # Build is gone too — CASCADE on printer_id.
    session.expire_all()
    with pytest.raises(NotFoundError):
        await build_svc.get_build(session, build_id)


async def test_source_project_set_null_on_project_delete(
    client: AsyncClient, session: AsyncSession
) -> None:
    pid = await _new_printer(session)
    proj_id = await _new_project(session, "to be deleted")
    build_id = await _make_build(session, pid, name="x", source_project_id=proj_id)

    await project_svc.delete_project(session, proj_id)
    await session.commit()

    body = await _read_build(session, build_id)
    assert body.source_project is None
    assert body.source_project_id is None


async def test_printers_list_links_to_detail(client: AsyncClient, session: AsyncSession) -> None:
    pid = await _new_printer(session, "X1")
    listing = await client.get("/printers")
    assert listing.status_code == 200
    assert f'href="/printers/{pid}"' in listing.text


async def test_update_link_qty_via_ui(client: AsyncClient, session: AsyncSession) -> None:
    pid = await _new_printer(session)
    mid = await _new_model(session, "feet")
    build_id = await _make_build(session, pid, name="Feet")
    await _link_model(session, build_id, mid, qty=1)

    update = await client.post(
        f"/printers/{pid}/builds/{build_id}/models/{mid}",
        data={"qty": "4", "notes": "corners"},
        follow_redirects=False,
    )
    assert update.status_code == 303

    full = await _read_build(session, build_id)
    link = full.model_links[0]
    assert link.qty == 4
    assert link.notes == "corners"
