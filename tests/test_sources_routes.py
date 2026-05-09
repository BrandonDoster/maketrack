from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import SpoolmanSourceFactory, persist


async def test_create_source_via_api(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/sources",
        json={
            "type": "spoolman",
            "name": "home",
            "base_url": "http://localhost:7912",
            "ttl_seconds": 3600,
            "enabled": True,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["type"] == "spoolman"
    assert body["enabled"] is True


async def test_list_sources(client: AsyncClient, session: AsyncSession) -> None:
    await persist(session, SpoolmanSourceFactory(name="a"))
    await persist(session, SpoolmanSourceFactory(name="b"))
    await session.commit()

    resp = await client.get("/api/sources")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_disable_source_archives_filaments(
    client: AsyncClient, session: AsyncSession
) -> None:
    src = await persist(session, SpoolmanSourceFactory())
    from maketrack.models.filament import Filament

    f = Filament(source="spoolman", external_id="1", name="X")
    session.add(f)
    await session.commit()

    resp = await client.patch(f"/api/sources/{src.id}", json={"enabled": False})
    assert resp.status_code == 200

    await session.refresh(f)
    assert f.archived_at is not None


async def test_invalid_source_type_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/sources",
        json={"type": "octoprint", "name": "x"},
    )
    assert resp.status_code == 422
