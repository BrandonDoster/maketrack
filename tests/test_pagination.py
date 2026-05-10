"""Pagination across the filament / inventory / model list pages."""

from httpx import AsyncClient

from maketrack.services._pagination import DEFAULT_PAGE_SIZE
from tests.factories import InventoryItemFactory, LocalFilamentFactory, persist

# ── Page math ─────────────────────────────────────────────────────────────


def test_page_math_at_edges() -> None:
    from maketrack.services._pagination import Page, normalize_page

    p = Page(items=list(range(50)), total=120, page=1, page_size=50)
    assert p.has_prev is False
    assert p.has_next is True
    assert p.total_pages == 3
    assert p.first_index == 1
    assert p.last_index == 50

    p2 = Page(items=list(range(50)), total=120, page=2, page_size=50)
    assert p2.has_prev is True
    assert p2.has_next is True
    assert (p2.first_index, p2.last_index) == (51, 100)

    p3 = Page(items=list(range(20)), total=120, page=3, page_size=50)
    assert p3.has_prev is True
    assert p3.has_next is False
    assert (p3.first_index, p3.last_index) == (101, 120)

    empty = Page(items=[], total=0, page=1, page_size=50)
    assert empty.total_pages == 1
    assert empty.first_index == 0
    assert (
        empty.last_index == -1
    )  # acceptable since the partial only renders when total > page_size

    assert normalize_page(None, 100) == 1
    assert normalize_page(99, 100, page_size=50) == 2  # clamped to last page
    assert normalize_page(0, 100) == 1
    assert normalize_page(2, 0) == 1  # nothing to page through


# ── filaments ─────────────────────────────────────────────────────────────


async def test_filaments_first_page_returns_default_page_size(client: AsyncClient, session) -> None:
    # Seed enough rows to span two pages.
    for i in range(DEFAULT_PAGE_SIZE + 5):
        await persist(session, LocalFilamentFactory(name=f"Spool-{i:03d}"))
    await session.commit()

    resp = await client.get("/filaments")
    # Page-of-pages footer says "X total · page 1 of 2"
    assert "page 1 of 2" in resp.text
    assert "Next" in resp.text
    # The footer chip is reachable as a link, not just disabled markup.
    assert "?page=2" in resp.text or "page=2" in resp.text


async def test_filaments_second_page_skips_first_50(client: AsyncClient, session) -> None:
    for i in range(DEFAULT_PAGE_SIZE + 3):
        await persist(session, LocalFilamentFactory(name=f"Spool-{i:03d}"))
    await session.commit()

    resp = await client.get("/filaments?page=2")
    # First 50 sorted by id are 0..49 — those should NOT be on page 2.
    assert "Spool-000" not in resp.text
    assert "Spool-049" not in resp.text
    # Tail of the table is on page 2.
    assert "Spool-050" in resp.text
    assert "Spool-052" in resp.text
    # Prev chip live, Next disabled (only 53 rows total).
    assert "page 2 of 2" in resp.text


async def test_filaments_pagination_preserves_search(client: AsyncClient, session) -> None:
    # Two distinct prefixes; only one matches the search.
    for i in range(60):
        await persist(session, LocalFilamentFactory(name=f"Voron-{i:03d}"))
    for i in range(5):
        await persist(session, LocalFilamentFactory(name=f"Other-{i:03d}"))
    await session.commit()

    resp = await client.get("/filaments?q=voron&page=2")
    assert "Voron-050" in resp.text
    # Prev/next URLs carry the search forward. Jinja autoescapes `&` to
    # `&amp;` in HTML attribute output, which is correct — accept either.
    assert "q=voron&amp;page=1" in resp.text or "q=voron&page=1" in resp.text


async def test_filaments_no_pagination_footer_when_under_threshold(
    client: AsyncClient, session
) -> None:
    """When total fits on one page, the partial renders nothing."""
    await persist(session, LocalFilamentFactory(name="Just one"))
    await session.commit()
    resp = await client.get("/filaments")
    # Page footer copy is absent; "Just one" is visible.
    assert "Just one" in resp.text
    assert "page 1 of" not in resp.text


async def test_filaments_out_of_range_page_clamps_to_last(client: AsyncClient, session) -> None:
    for i in range(60):
        await persist(session, LocalFilamentFactory(name=f"Spool-{i:03d}"))
    await session.commit()

    resp = await client.get("/filaments?page=99")
    # Clamped to page 2 (the last real page), not a 404.
    assert resp.status_code == 200
    assert "page 2 of 2" in resp.text


# ── inventory ─────────────────────────────────────────────────────────────


async def test_inventory_pagination(client: AsyncClient, session) -> None:
    for i in range(60):
        await persist(session, InventoryItemFactory(name=f"Bolt-{i:03d}"))
    await session.commit()

    resp_page1 = await client.get("/inventory")
    assert "page 1 of 2" in resp_page1.text
    assert "Bolt-000" in resp_page1.text

    resp_page2 = await client.get("/inventory?page=2")
    assert "Bolt-000" not in resp_page2.text
    assert "Bolt-050" in resp_page2.text


async def test_inventory_pagination_preserves_below_reorder(client: AsyncClient, session) -> None:
    # 60 below-reorder items + 5 fully stocked.
    for i in range(60):
        await persist(
            session,
            InventoryItemFactory(name=f"Low-{i:03d}", quantity=0, reorder_threshold=5),
        )
    for i in range(5):
        await persist(session, InventoryItemFactory(name=f"OK-{i:03d}", quantity=100))
    await session.commit()

    resp = await client.get("/inventory?below_reorder=true&page=2")
    # Only the Low-prefixed items make it past the filter; only those past
    # index 49 land on page 2.
    assert "OK-000" not in resp.text
    assert "Low-050" in resp.text
    # Prev URL carries the filter. Jinja autoescapes `&` to `&amp;`.
    assert "below_reorder=true&amp;page=1" in resp.text or "below_reorder=true&page=1" in resp.text


# ── models ────────────────────────────────────────────────────────────────


async def test_models_pagination(client: AsyncClient) -> None:
    for i in range(55):
        await client.post("/api/models", json={"name": f"Bracket-{i:03d}"})

    resp = await client.get("/models?view=details")
    # Page footer present + clickable Next.
    assert "page 1 of 2" in resp.text
    assert "page=2" in resp.text


async def test_models_pagination_preserves_view_and_filter(
    client: AsyncClient,
) -> None:
    # 55 standalone library models + a project that owns one.
    for i in range(55):
        await client.post("/api/models", json={"name": f"Library-{i:03d}"})
    proj = (await client.post("/api/projects", json={"name": "P"})).json()["id"]
    in_proj = (await client.post("/api/models", json={"name": "ProjPart"})).json()["id"]
    await client.post(f"/api/projects/{proj}/models", json={"model_id": in_proj})

    resp = await client.get("/models?view=details&hide_project_models=true&page=2")
    # The footer's prev/next preserve view + filter.
    assert "view=details" in resp.text
    assert "hide_project_models=true" in resp.text
    # ProjPart was filtered out, so it's nowhere on page 2 either.
    assert "ProjPart" not in resp.text
