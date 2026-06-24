"""Locations: structured bin/shelf/drawer table that replaced the
inventory_items.location free-text field."""

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.schemas.location import LocationCreate, LocationUpdate
from maketrack.services import inventory as inventory_svc
from maketrack.services import locations as location_svc
from tests.factories import make_inventory_item


async def _create(session: AsyncSession, name: str, kind: str = "bin") -> int:
    loc = await location_svc.create_location(session, LocationCreate(name=name, kind=kind))
    await session.commit()
    return loc.id


async def test_create_list_get_location(session: AsyncSession) -> None:
    lid = await _create(session, "Shelf 4", "shelf")

    listed = await location_svc.list_locations(session)
    assert any(loc.id == lid for loc in listed)

    one = await location_svc.get_location(session, lid)
    assert one.name == "Shelf 4"
    assert one.kind == "shelf"


async def test_duplicate_name_rejected(session: AsyncSession) -> None:
    await _create(session, "Bin A3")
    with pytest.raises(location_svc.DuplicateLocationError):
        await location_svc.create_location(session, LocationCreate(name="Bin A3", kind="bin"))


async def test_invalid_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        LocationCreate(name="x", kind="warehouse")


async def test_update_location(session: AsyncSession) -> None:
    lid = await _create(session, "Drawer 1", "drawer")
    updated = await location_svc.update_location(session, lid, LocationUpdate(name="Drawer 1A"))
    await session.commit()
    assert updated.name == "Drawer 1A"


async def test_delete_location_sets_inventory_fk_null(session: AsyncSession) -> None:
    lid = await _create(session, "Bin 99")
    item = await make_inventory_item(session, name="thing", location_id=lid, quantity=1)

    await location_svc.delete_location(session, lid)
    await session.commit()

    await session.refresh(item)
    assert item.location_id is None


async def test_locations_settings_page_renders(client: AsyncClient, session: AsyncSession) -> None:
    await _create(session, "Bin C7")

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


async def test_locations_settings_edit_then_save(client: AsyncClient, session: AsyncSession) -> None:
    lid = await _create(session, "Bin Z1")

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


async def test_locations_settings_delete(client: AsyncClient, session: AsyncSession) -> None:
    lid = await _create(session, "Bin K1")

    resp = await client.post(f"/settings/locations/{lid}/delete", follow_redirects=False)
    assert resp.status_code == 303

    page = await client.get("/settings/locations")
    assert "Bin K1" not in page.text


async def test_inventory_form_renders_location_select(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _create(session, "Bin Q9", "bin")
    resp = await client.get("/inventory/new")
    assert resp.status_code == 200
    assert 'name="location_id"' in resp.text
    assert "Bin Q9" in resp.text
    assert "Manage locations" in resp.text


async def test_inventory_list_renders_location_name(
    client: AsyncClient, session: AsyncSession
) -> None:
    lid = await _create(session, "Bin M5")
    await make_inventory_item(session, name="M5 Bolt", location_id=lid, quantity=25)

    listing = await client.get("/inventory")
    assert listing.status_code == 200
    assert "Bin M5" in listing.text


async def test_inventory_form_post_with_location_redirects(
    client: AsyncClient, session: AsyncSession
) -> None:
    lid = await _create(session, "Bin Y8")
    resp = await client.post(
        "/inventory",
        data={"name": "Heatset", "quantity": "10", "location_id": str(lid)},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    items = await inventory_svc.list_items(session)
    assert any(i.name == "Heatset" and i.location_id == lid for i in items)


async def test_settings_page_links_to_locations(client: AsyncClient) -> None:
    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "/settings/locations" in resp.text
