from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import LocalFilamentFactory, RemoteFilamentFactory, persist


async def test_create_then_get_filament(client: AsyncClient) -> None:
    create = await client.post(
        "/api/filaments",
        json={
            "name": "Black PLA",
            "material": "PLA",
            "color_hex": "#000000",
            "diameter_mm": 1.75,
            "total_weight_g": 1000,
            "remaining_weight_g": 1000,
        },
    )
    assert create.status_code == 201, create.text
    created = create.json()
    assert created["source"] == "local"
    assert created["material"] == "PLA"

    fetched = await client.get(f"/api/filaments/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


async def test_list_filaments(client: AsyncClient, session: AsyncSession) -> None:
    await persist(session, LocalFilamentFactory(material="PLA"))
    await persist(session, LocalFilamentFactory(material="PETG"))
    await session.commit()

    resp = await client.get("/api/filaments")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    pla = await client.get("/api/filaments?material=PLA")
    assert pla.status_code == 200
    assert len(pla.json()) == 1


async def test_patch_remote_filament_returns_409(
    client: AsyncClient, session: AsyncSession
) -> None:
    remote = await persist(session, RemoteFilamentFactory())
    await session.commit()

    resp = await client.patch(
        f"/api/filaments/{remote.id}",
        json={"name": "tampered"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "remote_filament_readonly"
    assert body["source"] == "spoolman"
    assert body["external_url"] == remote.external_url


async def test_patch_missing_returns_404(client: AsyncClient) -> None:
    resp = await client.patch("/api/filaments/999999", json={"name": "x"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


async def test_invalid_color_hex_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/filaments",
        json={"color_hex": "not-a-color"},
    )
    assert resp.status_code == 422
