"""Search + filter coverage for the five list pages."""

from httpx import AsyncClient

from tests.factories import (
    InventoryItemFactory,
    LocalFilamentFactory,
    PrinterFactory,
    persist,
)

# ── filaments ─────────────────────────────────────────────────────────────


async def test_filaments_search_filters_by_name(client: AsyncClient, session) -> None:
    await persist(session, LocalFilamentFactory(name="PLA Black", material="PLA"))
    await persist(session, LocalFilamentFactory(name="PETG White", material="PETG"))
    await session.commit()

    resp = await client.get("/filaments?q=BLACK")  # case-insensitive
    assert resp.status_code == 200
    assert "PLA Black" in resp.text
    assert "PETG White" not in resp.text


async def test_filaments_filter_by_material(client: AsyncClient, session) -> None:
    await persist(session, LocalFilamentFactory(name="PLA Black", material="PLA"))
    await persist(session, LocalFilamentFactory(name="PETG Clear", material="PETG"))
    await session.commit()

    resp = await client.get("/filaments?material=PETG")
    assert "PETG Clear" in resp.text
    assert "PLA Black" not in resp.text


async def test_filaments_empty_state_with_query(client: AsyncClient) -> None:
    resp = await client.get("/filaments?q=nonexistent")
    assert resp.status_code == 200
    assert "No matches" in resp.text
    assert "nonexistent" in resp.text


async def test_filaments_clear_link_visible_when_filtered(
    client: AsyncClient,
) -> None:
    resp = await client.get("/filaments?q=foo")
    assert ">Clear<" in resp.text


# ── inventory ─────────────────────────────────────────────────────────────


async def test_inventory_search(client: AsyncClient, session) -> None:
    await persist(session, InventoryItemFactory(name="M3x12 SHCS"))
    await persist(session, InventoryItemFactory(name="Heatset M3"))
    await session.commit()

    resp = await client.get("/inventory?q=SHCS")
    assert "M3x12 SHCS" in resp.text
    assert "Heatset" not in resp.text


async def test_inventory_filter_by_category(client: AsyncClient, session) -> None:
    await persist(session, InventoryItemFactory(name="Bolt", category="hardware"))
    await persist(session, InventoryItemFactory(name="Wire", category="electronic"))
    await session.commit()

    resp = await client.get("/inventory?category=hardware")
    assert "Bolt" in resp.text
    assert "Wire" not in resp.text


async def test_inventory_below_reorder_filter(client: AsyncClient, session) -> None:
    await persist(
        session,
        InventoryItemFactory(name="Plenty", quantity=100, reorder_threshold=10),
    )
    await persist(
        session,
        InventoryItemFactory(name="LowStock", quantity=2, reorder_threshold=10),
    )
    await session.commit()

    resp = await client.get("/inventory?below_reorder=true")
    assert "LowStock" in resp.text
    assert "Plenty" not in resp.text


# ── printers ──────────────────────────────────────────────────────────────


async def test_printers_search(client: AsyncClient, session) -> None:
    await persist(session, PrinterFactory(name="Voron 2.4"))
    await persist(session, PrinterFactory(name="Bambu X1C"))
    await session.commit()

    resp = await client.get("/printers?q=voron")
    assert "Voron" in resp.text
    assert "Bambu" not in resp.text


async def test_printers_empty_state_with_query(client: AsyncClient) -> None:
    resp = await client.get("/printers?q=nonexistent")
    assert "No matches" in resp.text


# ── projects ──────────────────────────────────────────────────────────────


async def test_projects_search(client: AsyncClient) -> None:
    await client.post("/api/projects", json={"name": "Voron Build"})
    await client.post("/api/projects", json={"name": "Bambu Mod"})

    resp = await client.get("/projects?q=voron")
    assert "Voron Build" in resp.text
    assert "Bambu Mod" not in resp.text


async def test_projects_search_preserves_status_filter(client: AsyncClient) -> None:
    """Status chips link with the current ?q= preserved, and the search form
    keeps the status as a hidden input."""
    a = await client.post("/api/projects", json={"name": "Active Voron"})
    await client.patch(f"/api/projects/{a.json()['id']}", json={"status": "printing"})
    await client.post("/api/projects", json={"name": "Idle Voron"})

    resp = await client.get("/projects?status=printing&q=voron")
    assert "Active Voron" in resp.text
    assert "Idle Voron" not in resp.text
    # Search form retains the status hidden input.
    assert 'name="status" value="printing"' in resp.text


# ── models ────────────────────────────────────────────────────────────────


async def test_models_search(client: AsyncClient) -> None:
    await client.post("/api/models", json={"name": "Voron Filter Mount"})
    await client.post("/api/models", json={"name": "Y-Belt Tensioner"})

    resp = await client.get("/models?q=voron")
    assert "Voron Filter Mount" in resp.text
    assert "Y-Belt Tensioner" not in resp.text


async def test_models_search_preserves_view_and_filter(client: AsyncClient) -> None:
    """The view-switch links and toolbar should keep the search query."""
    await client.post("/api/models", json={"name": "Heroic Bracket"})

    resp = await client.get("/models?view=details&q=heroic")
    # View links propagate q
    assert "view=cards&amp;q=heroic" in resp.text or "view=cards&q=heroic" in resp.text
    # Empty-state link strips q
    # And the search form has the right hidden inputs to preserve view.
    assert 'name="view" value="details"' in resp.text


async def test_models_empty_state_clear_search_link(client: AsyncClient) -> None:
    resp = await client.get("/models?q=nonsense")
    assert "No matches" in resp.text
    assert "Clear search" in resp.text
