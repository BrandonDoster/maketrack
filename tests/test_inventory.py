from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import InventoryItemFactory, persist


async def test_create_inventory_item(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/inventory",
        json={
            "name": "M3x12 SHCS",
            "category": "hardware",
            "quantity": 200,
            "reorder_threshold": 50,
            "unit": "each",
            "vendor": "McMaster",
            "vendor_sku": "92095A192",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "M3x12 SHCS"
    assert body["quantity"] == 200


async def test_list_inventory_filters_by_category(
    client: AsyncClient, session: AsyncSession
) -> None:
    await persist(session, InventoryItemFactory(category="hardware", name="bolt"))
    await persist(session, InventoryItemFactory(category="electronic", name="resistor"))
    await session.commit()

    resp = await client.get("/api/inventory?category=hardware")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "bolt"


async def test_invalid_category_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/inventory",
        json={"name": "x", "category": "nonsense"},
    )
    assert resp.status_code == 422


async def test_negative_quantity_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/inventory",
        json={"name": "x", "quantity": -1},
    )
    assert resp.status_code == 422


async def test_update_and_delete_inventory(client: AsyncClient, session: AsyncSession) -> None:
    item = await persist(session, InventoryItemFactory())
    await session.commit()

    patch = await client.patch(f"/api/inventory/{item.id}", json={"quantity": 5})
    assert patch.status_code == 200
    assert patch.json()["quantity"] == 5

    delete = await client.delete(f"/api/inventory/{item.id}")
    assert delete.status_code == 204

    missing = await client.get(f"/api/inventory/{item.id}")
    assert missing.status_code == 404


async def test_inventory_list_renders(client: AsyncClient, session: AsyncSession) -> None:
    await persist(
        session,
        InventoryItemFactory(name="M5 Heatset", quantity=2, reorder_threshold=10),
    )
    await session.commit()

    resp = await client.get("/inventory")
    assert resp.status_code == 200
    assert "M5 Heatset" in resp.text
    assert "reorder" in resp.text  # below threshold so the badge shows


async def test_create_inventory_via_form(client: AsyncClient) -> None:
    resp = await client.post(
        "/inventory",
        data={
            "name": "Form Bolt",
            "category": "hardware",
            "quantity": "10",
            "unit": "each",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    listing = await client.get("/inventory")
    assert "Form Bolt" in listing.text
