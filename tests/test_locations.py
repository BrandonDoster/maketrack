"""Locations: structured bin/shelf/drawer table that replaced the
inventory_items.location free-text field."""

from httpx import AsyncClient


async def _create(client: AsyncClient, name: str, kind: str = "bin") -> int:
    resp = await client.post("/api/locations", json={"name": name, "kind": kind})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_create_list_get_location(client: AsyncClient) -> None:
    lid = await _create(client, "Shelf 4", "shelf")

    listed = await client.get("/api/locations")
    assert listed.status_code == 200
    assert any(loc["id"] == lid for loc in listed.json())

    one = await client.get(f"/api/locations/{lid}")
    assert one.status_code == 200
    body = one.json()
    assert body["name"] == "Shelf 4"
    assert body["kind"] == "shelf"


async def test_duplicate_name_rejected(client: AsyncClient) -> None:
    await _create(client, "Bin A3")
    dup = await client.post("/api/locations", json={"name": "Bin A3", "kind": "bin"})
    assert dup.status_code == 409


async def test_invalid_kind_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/locations", json={"name": "x", "kind": "warehouse"})
    assert resp.status_code == 422


async def test_update_location(client: AsyncClient) -> None:
    lid = await _create(client, "Drawer 1", "drawer")
    patched = await client.patch(f"/api/locations/{lid}", json={"name": "Drawer 1A"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Drawer 1A"


async def test_delete_location_sets_inventory_fk_null(client: AsyncClient) -> None:
    lid = await _create(client, "Bin 99")
    item = await client.post(
        "/api/inventory",
        json={"name": "thing", "location_id": lid, "quantity": 1},
    )
    item_id = item.json()["id"]

    deleted = await client.delete(f"/api/locations/{lid}")
    assert deleted.status_code == 204

    refreshed = await client.get(f"/api/inventory/{item_id}")
    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["location_id"] is None
    assert body["location"] is None


async def test_locations_settings_page_renders(client: AsyncClient) -> None:
    await _create(client, "Bin C7")

    page = await client.get("/settings/locations")
    assert page.status_code == 200
    assert "Bin C7" in page.text
    # Form for adding new locations is on the page.
    assert 'action="/settings/locations"' in page.text


async def test_locations_settings_create_redirects(client: AsyncClient) -> None:
    resp = await client.post(
        "/settings/locations",
        data={"name": "Shelf 9", "kind": "shelf"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/locations"

    page = await client.get("/settings/locations")
    assert "Shelf 9" in page.text


async def test_locations_settings_edit_then_save(client: AsyncClient) -> None:
    lid = await _create(client, "Bin Z1")

    edit_page = await client.get(f"/settings/locations/{lid}/edit")
    assert edit_page.status_code == 200
    assert "Bin Z1" in edit_page.text

    saved = await client.post(
        f"/settings/locations/{lid}",
        data={"name": "Bin Z2", "kind": "bin"},
        follow_redirects=False,
    )
    assert saved.status_code == 303

    listing = await client.get("/settings/locations")
    assert "Bin Z2" in listing.text
    assert "Bin Z1" not in listing.text


async def test_locations_settings_delete(client: AsyncClient) -> None:
    lid = await _create(client, "Bin K1")

    resp = await client.post(f"/settings/locations/{lid}/delete", follow_redirects=False)
    assert resp.status_code == 303

    page = await client.get("/settings/locations")
    assert "Bin K1" not in page.text


async def test_inventory_form_renders_location_select(client: AsyncClient) -> None:
    await _create(client, "Bin Q9", "bin")
    resp = await client.get("/inventory/new")
    assert resp.status_code == 200
    assert 'name="location_id"' in resp.text
    assert "Bin Q9" in resp.text
    assert "Manage locations" in resp.text


async def test_inventory_list_renders_location_name(client: AsyncClient) -> None:
    lid = await _create(client, "Bin M5")
    await client.post(
        "/api/inventory",
        json={"name": "M5 Bolt", "location_id": lid, "quantity": 25},
    )

    listing = await client.get("/inventory")
    assert listing.status_code == 200
    assert "Bin M5" in listing.text


async def test_inventory_form_post_with_location_redirects(client: AsyncClient) -> None:
    lid = await _create(client, "Bin Y8")
    resp = await client.post(
        "/inventory",
        data={"name": "Heatset", "quantity": "10", "location_id": str(lid)},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    api = await client.get("/api/inventory")
    items = api.json()
    assert any(i["name"] == "Heatset" and i["location_id"] == lid for i in items)


async def test_settings_page_links_to_locations(client: AsyncClient) -> None:
    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "/settings/locations" in resp.text
