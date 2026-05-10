import io

from httpx import AsyncClient

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\x00"
    b"\x01\xfd\xc7\xa6X\xc0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _stl_bytes() -> bytes:
    return b"\x00" * 80 + (0).to_bytes(4, "little")


# ── unlinked custom BOM items ──────────────────────────────────────────────


async def test_add_custom_bom_item_without_inventory(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]

    resp = await client.post(
        f"/api/projects/{pid}/items",
        json={"name": "M3x12 SHCS", "unit": "each", "qty_required": 20},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["inventory_item_id"] is None
    assert body["name"] == "M3x12 SHCS"
    assert body["display_name"] == "M3x12 SHCS"


async def test_bom_unlinked_row_has_null_on_hand_and_full_still_to_buy(
    client: AsyncClient,
) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    await client.post(
        f"/api/projects/{pid}/items",
        json={"name": "Mystery Bolt", "qty_required": 50, "qty_consumed": 10},
    )

    bom = (await client.get(f"/api/projects/{pid}/bom")).json()
    assert len(bom) == 1
    row = bom[0]
    assert row["inventory_item_id"] is None
    assert row["on_hand"] is None
    assert row["still_needed_for_project"] == 40
    assert row["still_to_buy"] == 40


async def test_add_bom_with_neither_id_nor_name_fails(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    resp = await client.post(f"/api/projects/{pid}/items", json={"qty_required": 5})
    assert resp.status_code == 400


async def test_late_link_inventory_to_custom_bom(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    inv = await client.post("/api/inventory", json={"name": "M3x12 SHCS", "quantity": 5})
    iid = inv.json()["id"]
    custom = await client.post(
        f"/api/projects/{pid}/items",
        json={"name": "M3x12 SHCS", "qty_required": 10},
    )
    link_id = custom.json()["id"]

    linked = await client.post(f"/api/projects/{pid}/items/{link_id}/link/{iid}")
    assert linked.status_code == 200
    assert linked.json()["inventory_item_id"] == iid
    # Original typed name is preserved on the link as a record.
    assert linked.json()["name"] == "M3x12 SHCS"

    # BOM row now reflects on_hand from the linked inventory.
    bom = (await client.get(f"/api/projects/{pid}/bom")).json()
    assert bom[0]["on_hand"] == 5
    assert bom[0]["still_to_buy"] == 5


async def test_shopping_list_includes_unlinked_rows(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    await client.post(
        f"/api/projects/{pid}/items",
        json={"name": "Mystery Hardware", "qty_required": 12},
    )

    rows = (await client.get("/api/shopping-list")).json()
    names = [r["name"] for r in rows]
    assert "Mystery Hardware" in names
    mystery = next(r for r in rows if r["name"] == "Mystery Hardware")
    assert mystery["inventory_item_id"] is None
    assert mystery["still_to_buy"] == 12


# ── project file upload ────────────────────────────────────────────────────


async def test_project_file_upload_creates_models_and_links(
    client: AsyncClient,
) -> None:
    project = await client.post("/api/projects", json={"name": "Voron"})
    pid = project.json()["id"]

    resp = await client.post(
        f"/projects/{pid}/upload-files",
        files=[
            ("files", ("bracket.stl", io.BytesIO(_stl_bytes()), "model/stl")),
            ("files", ("nut_holder.stl", io.BytesIO(_stl_bytes()), "model/stl")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 303

    models_in_project = (await client.get(f"/api/projects/{pid}/models")).json()
    assert len(models_in_project) == 2
    names = sorted(m["model_name"] for m in models_in_project)
    assert names == ["bracket", "nut_holder"]


async def test_project_file_upload_skips_image_files(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    resp = await client.post(
        f"/projects/{pid}/upload-files",
        files=[("files", ("ignore_me.png", io.BytesIO(_PNG), "image/png"))],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # Image files don't become models on this endpoint — that's the photo flow.
    assert (await client.get(f"/api/projects/{pid}/models")).json() == []


# ── project photos ─────────────────────────────────────────────────────────


async def test_upload_cover_photo(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]

    resp = await client.post(
        f"/projects/{pid}/photo/cover",
        files={"file": ("cover.png", io.BytesIO(_PNG), "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    detail = await client.get(f"/projects/{pid}")
    # The detail page renders <img src="/media/projects/<uuid>.png"> for the cover.
    assert "/media/projects/" in detail.text


async def test_upload_completed_photo_separate_slot(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]

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


async def test_replace_photo_drops_old_file(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]

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


async def test_unknown_photo_kind_is_a_noop(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    resp = await client.post(
        f"/projects/{pid}/photo/sideways",
        files={"file": ("a.png", io.BytesIO(_PNG), "image/png")},
        follow_redirects=False,
    )
    # Redirects without persisting (unknown slot is rejected silently).
    assert resp.status_code == 303


# ── M6 polish: cover photo on list, inline qty, inline notes ──────────────


async def test_project_list_renders_cover_photo(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "Cover Test"})
    pid = project.json()["id"]
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


async def test_inline_qty_required_save(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    inv = await client.post("/api/inventory", json={"name": "Bolt", "quantity": 0})
    iid = inv.json()["id"]
    add = await client.post(
        f"/api/projects/{pid}/items",
        json={"inventory_item_id": iid, "qty_required": 10},
    )
    link_id = add.json()["id"]

    resp = await client.post(
        f"/projects/{pid}/items/{link_id}/qty",
        data={"qty_required": "25"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    bom = (await client.get(f"/api/projects/{pid}/bom")).json()
    assert bom[0]["still_needed_for_project"] == 25


async def test_inline_qty_consumed_save(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    inv = await client.post("/api/inventory", json={"name": "Bolt", "quantity": 100})
    iid = inv.json()["id"]
    add = await client.post(
        f"/api/projects/{pid}/items",
        json={"inventory_item_id": iid, "qty_required": 10},
    )
    link_id = add.json()["id"]

    await client.post(
        f"/projects/{pid}/items/{link_id}/qty",
        data={"qty_consumed": "4"},
        follow_redirects=False,
    )
    bom = (await client.get(f"/api/projects/{pid}/bom")).json()
    assert bom[0]["still_needed_for_project"] == 6  # 10 - 4


async def test_inline_qty_invalid_input_is_ignored(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    inv = await client.post("/api/inventory", json={"name": "Bolt"})
    iid = inv.json()["id"]
    add = await client.post(
        f"/api/projects/{pid}/items",
        json={"inventory_item_id": iid, "qty_required": 10},
    )
    link_id = add.json()["id"]

    resp = await client.post(
        f"/projects/{pid}/items/{link_id}/qty",
        data={"qty_required": "not-a-number"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    bom = (await client.get(f"/api/projects/{pid}/bom")).json()
    assert bom[0]["still_needed_for_project"] == 10  # unchanged


async def test_inline_notes_save(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]

    resp = await client.post(
        f"/projects/{pid}/notes",
        data={"notes": "ordered the heatsets, ETA Friday"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    fetched = (await client.get(f"/api/projects/{pid}")).json()
    assert fetched["notes"] == "ordered the heatsets, ETA Friday"


async def test_inline_notes_clears_on_empty(client: AsyncClient) -> None:
    project = await client.post("/api/projects", json={"name": "P"})
    pid = project.json()["id"]
    await client.post(
        f"/projects/{pid}/notes",
        data={"notes": "first pass"},
        follow_redirects=False,
    )
    await client.post(
        f"/projects/{pid}/notes",
        data={"notes": "   "},
        follow_redirects=False,
    )
    fetched = (await client.get(f"/api/projects/{pid}")).json()
    assert fetched["notes"] is None


async def test_detail_page_renders_inline_widgets(client: AsyncClient) -> None:
    """The detail page should show qty inputs (not just text) and a notes textarea."""
    project = await client.post("/api/projects", json={"name": "Widgets"})
    pid = project.json()["id"]
    inv = await client.post("/api/inventory", json={"name": "Bolt"})
    iid = inv.json()["id"]
    await client.post(
        f"/api/projects/{pid}/items",
        json={"inventory_item_id": iid, "qty_required": 5},
    )

    detail = await client.get(f"/projects/{pid}")
    assert detail.status_code == 200
    # The inline qty form posts to the qty endpoint per row.
    assert f"/projects/{pid}/items/" in detail.text
    assert "/qty" in detail.text
    # Notes form action is present.
    assert f'action="/projects/{pid}/notes"' in detail.text
