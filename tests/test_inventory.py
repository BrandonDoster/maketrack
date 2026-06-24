import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError
from maketrack.schemas.inventory import InventoryItemCreate, InventoryItemUpdate
from maketrack.services import inventory as inventory_svc
from tests.factories import InventoryItemFactory, persist


async def test_create_inventory_item(session: AsyncSession) -> None:
    item = await inventory_svc.create_item(
        session,
        InventoryItemCreate(
            name="M3x12 SHCS",
            category="hardware",
            quantity=200,
            reorder_threshold=50,
            unit="each",
            vendor="McMaster",
            vendor_sku="92095A192",
        ),
    )
    await session.commit()
    assert item.name == "M3x12 SHCS"
    assert item.quantity == 200


async def test_list_inventory_filters_by_category(session: AsyncSession) -> None:
    await persist(session, InventoryItemFactory(category="hardware", name="bolt"))
    await persist(session, InventoryItemFactory(category="electronic", name="resistor"))
    await session.commit()

    rows = await inventory_svc.list_items(session, category="hardware")
    assert len(rows) == 1
    assert rows[0].name == "bolt"


async def test_invalid_category_rejected() -> None:
    with pytest.raises(ValidationError):
        InventoryItemCreate(name="x", category="nonsense")


async def test_negative_quantity_rejected() -> None:
    with pytest.raises(ValidationError):
        InventoryItemCreate(name="x", quantity=-1)


async def test_update_and_delete_inventory(session: AsyncSession) -> None:
    item = await persist(session, InventoryItemFactory())
    await session.commit()

    updated = await inventory_svc.update_item(session, item.id, InventoryItemUpdate(quantity=5))
    await session.commit()
    assert updated.quantity == 5

    await inventory_svc.delete_item(session, item.id)
    await session.commit()

    with pytest.raises(NotFoundError):
        await inventory_svc.get_item(session, item.id)


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
