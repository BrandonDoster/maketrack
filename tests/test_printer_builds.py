"""Printer detail page, photo, and the per-printer build list — each
build can link to a project and to many models with qty + notes."""

import io

from httpx import AsyncClient

# 1x1 PNG so the multipart upload path actually exercises save_photo.
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\x00"
    b"\x01\xfd\xc7\xa6X\xc0\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _new_printer(client: AsyncClient, name: str = "Voron 0") -> int:
    resp = await client.post("/api/printers", json={"name": name, "model": "Voron 0.2"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_model(client: AsyncClient, name: str) -> int:
    resp = await client.post("/api/models", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_project(client: AsyncClient, name: str) -> int:
    resp = await client.post("/api/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_printer_detail_page_renders(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    resp = await client.get(f"/printers/{pid}")
    assert resp.status_code == 200
    assert "Voron 0" in resp.text
    assert "Build" in resp.text
    # Three add paths land on the detail page.
    assert ">Add model<" in resp.text
    assert ">Add project<" in resp.text
    assert ">Add custom<" in resp.text


async def test_printer_photo_upload_and_remove(client: AsyncClient) -> None:
    pid = await _new_printer(client)

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


async def test_create_build_via_api(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    proj_id = await _new_project(client, "Voron 0.2 build journal")

    resp = await client.post(
        f"/api/printers/{pid}/builds",
        json={"name": "PEI bed", "source_project_id": proj_id, "description": "smooth"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "PEI bed"
    assert body["source_project"]["id"] == proj_id
    assert body["source_project"]["name"] == "Voron 0.2 build journal"
    assert body["model_links"] == []


async def test_link_and_unlink_models(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    duct_id = await _new_model(client, "Stealthburner duct")
    fan_id = await _new_model(client, "5015 fan mount")

    create = await client.post(f"/api/printers/{pid}/builds", json={"name": "Cooling upgrade"})
    build_id = create.json()["id"]

    a = await client.post(
        f"/api/printer-builds/{build_id}/models",
        json={"model_id": duct_id, "qty": 1, "notes": "front"},
    )
    assert a.status_code == 201
    b = await client.post(
        f"/api/printer-builds/{build_id}/models",
        json={"model_id": fan_id, "qty": 2},
    )
    assert b.status_code == 201

    full = await client.get(f"/api/printer-builds/{build_id}")
    links = {link["model_id"]: link for link in full.json()["model_links"]}
    assert set(links) == {duct_id, fan_id}
    assert links[duct_id]["qty"] == 1
    assert links[duct_id]["notes"] == "front"
    assert links[duct_id]["model"]["name"] == "Stealthburner duct"
    assert links[fan_id]["qty"] == 2

    unlink = await client.delete(f"/api/printer-builds/{build_id}/models/{fan_id}")
    assert unlink.status_code == 204

    full = await client.get(f"/api/printer-builds/{build_id}")
    assert [link["model_id"] for link in full.json()["model_links"]] == [duct_id]


async def test_link_unknown_model_404s(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    create = await client.post(f"/api/printers/{pid}/builds", json={"name": "x"})
    build_id = create.json()["id"]

    resp = await client.post(
        f"/api/printer-builds/{build_id}/models", json={"model_id": 99999, "qty": 1}
    )
    assert resp.status_code == 404


async def test_qty_must_be_positive(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    mid = await _new_model(client, "x")
    create = await client.post(f"/api/printers/{pid}/builds", json={"name": "x"})
    build_id = create.json()["id"]

    resp = await client.post(
        f"/api/printer-builds/{build_id}/models",
        json={"model_id": mid, "qty": 0},
    )
    assert resp.status_code == 422


async def test_ui_add_model_path_seeds_name_and_link(client: AsyncClient) -> None:
    """Picking a model from the inline form creates a build named after
    the model AND auto-links the model — no name typing required."""
    pid = await _new_printer(client)
    mid = await _new_model(client, "Stealthburner duct")

    create = await client.post(
        f"/printers/{pid}/builds",
        data={"model_id": str(mid)},
        follow_redirects=False,
    )
    assert create.status_code == 303

    builds = (await client.get(f"/api/printers/{pid}/builds")).json()
    assert len(builds) == 1
    assert builds[0]["name"] == "Stealthburner duct"
    links = builds[0]["model_links"]
    assert len(links) == 1
    assert links[0]["model_id"] == mid
    assert links[0]["qty"] == 1


async def test_ui_add_project_path_uses_project_name(client: AsyncClient) -> None:
    """Picking a project doesn't require typing a build name — the
    project's own name is used."""
    pid = await _new_printer(client)
    proj_id = await _new_project(client, "Skirts journal")

    create = await client.post(
        f"/printers/{pid}/builds",
        data={"source_project_id": str(proj_id)},
        follow_redirects=False,
    )
    assert create.status_code == 303

    builds = (await client.get(f"/api/printers/{pid}/builds")).json()
    assert len(builds) == 1
    assert builds[0]["name"] == "Skirts journal"
    assert builds[0]["source_project"]["id"] == proj_id
    assert builds[0]["model_links"] == []

    detail = await client.get(f"/printers/{pid}")
    assert f'href="/projects/{proj_id}"' in detail.text


async def test_ui_add_custom_name_path(client: AsyncClient) -> None:
    """Custom name path: just text, no model or project — for things
    like 'Custom wiring' that don't link to either."""
    pid = await _new_printer(client)

    create = await client.post(
        f"/printers/{pid}/builds",
        data={"name": "Custom wiring"},
        follow_redirects=False,
    )
    assert create.status_code == 303

    builds = (await client.get(f"/api/printers/{pid}/builds")).json()
    assert len(builds) == 1
    assert builds[0]["name"] == "Custom wiring"
    assert builds[0]["source_project"] is None
    assert builds[0]["model_links"] == []


async def test_ui_link_more_models_via_edit_page(client: AsyncClient) -> None:
    """Once a build exists (created from any path), the edit page lets
    you keep adding models with qty + notes."""
    pid = await _new_printer(client)
    mid = await _new_model(client, "skirt panel")

    create = await client.post(
        f"/printers/{pid}/builds",
        data={"name": "Skirts"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    build_id = (await client.get(f"/api/printers/{pid}/builds")).json()[0]["id"]

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


async def test_ui_empty_form_is_a_noop(client: AsyncClient) -> None:
    """Submitting all three forms blank does nothing rather than 422'ing."""
    pid = await _new_printer(client)

    resp = await client.post(f"/printers/{pid}/builds", data={}, follow_redirects=False)
    assert resp.status_code == 303

    builds = (await client.get(f"/api/printers/{pid}/builds")).json()
    assert builds == []


async def test_ui_build_photo_upload_and_remove(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    create = await client.post(
        f"/printers/{pid}/builds",
        data={"name": "Cover plate"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    builds = await client.get(f"/api/printers/{pid}/builds")
    build_id = builds.json()[0]["id"]

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


async def test_delete_build_redirects_to_detail(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    create = await client.post(f"/api/printers/{pid}/builds", json={"name": "x"})
    build_id = create.json()["id"]

    resp = await client.post(f"/printers/{pid}/builds/{build_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/printers/{pid}"

    listed = await client.get(f"/api/printers/{pid}/builds")
    assert listed.json() == []


async def test_deleting_printer_cascades_builds(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    mid = await _new_model(client, "duct")
    create = await client.post(f"/api/printers/{pid}/builds", json={"name": "x"})
    build_id = create.json()["id"]
    await client.post(f"/api/printer-builds/{build_id}/models", json={"model_id": mid, "qty": 1})

    deleted = await client.delete(f"/api/printers/{pid}")
    assert deleted.status_code == 204

    # Build is gone too — CASCADE on printer_id.
    gone = await client.get(f"/api/printer-builds/{build_id}")
    assert gone.status_code == 404


async def test_source_project_set_null_on_project_delete(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    proj_id = await _new_project(client, "to be deleted")
    create = await client.post(
        f"/api/printers/{pid}/builds",
        json={"name": "x", "source_project_id": proj_id},
    )
    build_id = create.json()["id"]

    deleted = await client.delete(f"/api/projects/{proj_id}")
    assert deleted.status_code == 204

    full = await client.get(f"/api/printer-builds/{build_id}")
    assert full.status_code == 200
    body = full.json()
    assert body["source_project"] is None
    assert body["source_project_id"] is None


async def test_printers_list_links_to_detail(client: AsyncClient) -> None:
    pid = await _new_printer(client, "X1")
    listing = await client.get("/printers")
    assert listing.status_code == 200
    assert f'href="/printers/{pid}"' in listing.text


async def test_update_link_qty_via_ui(client: AsyncClient) -> None:
    pid = await _new_printer(client)
    mid = await _new_model(client, "feet")
    create = await client.post(f"/api/printers/{pid}/builds", json={"name": "Feet"})
    build_id = create.json()["id"]
    await client.post(f"/api/printer-builds/{build_id}/models", json={"model_id": mid, "qty": 1})

    update = await client.post(
        f"/printers/{pid}/builds/{build_id}/models/{mid}",
        data={"qty": "4", "notes": "corners"},
        follow_redirects=False,
    )
    assert update.status_code == 303

    full = await client.get(f"/api/printer-builds/{build_id}")
    link = full.json()["model_links"][0]
    assert link["qty"] == 4
    assert link["notes"] == "corners"
