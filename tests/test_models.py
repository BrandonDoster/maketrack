from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.services.models import decode_tags


async def test_create_model(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/models",
        json={
            "name": "Voron Filter Mount",
            "description": "Mount for the Nevermore filter",
            "source_type": "printables",
            "source_url": "https://www.printables.com/model/12345",
            "tags": ["voron", "filter"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Voron Filter Mount"
    assert body["tags"] == ["voron", "filter"]


async def test_tags_round_trip_via_db(client: AsyncClient, session: AsyncSession) -> None:
    create = await client.post("/api/models", json={"name": "Tagged", "tags": ["a", "b", "c"]})
    model_id = create.json()["id"]

    # Re-read directly from the DB to make sure tags persisted as JSON.
    from maketrack.models.model import Model

    row = await session.get(Model, model_id)
    assert row is not None
    assert row.tags is not None
    assert decode_tags(row.tags) == ["a", "b", "c"]


async def test_list_filter_by_tag(client: AsyncClient) -> None:
    await client.post("/api/models", json={"name": "A", "tags": ["foo"]})
    await client.post("/api/models", json={"name": "B", "tags": ["bar"]})
    await client.post("/api/models", json={"name": "C", "tags": ["foo", "bar"]})

    resp = await client.get("/api/models?tag=foo")
    names = sorted(m["name"] for m in resp.json())
    assert names == ["A", "C"]


async def test_invalid_source_type_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/models", json={"name": "X", "source_type": "thingyverse"})
    assert resp.status_code == 422


async def test_update_model(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "Original"})
    mid = create.json()["id"]

    patch = await client.patch(f"/api/models/{mid}", json={"name": "Renamed", "tags": ["x"]})
    assert patch.status_code == 200
    body = patch.json()
    assert body["name"] == "Renamed"
    assert body["tags"] == ["x"]


async def test_models_list_renders(client: AsyncClient) -> None:
    await client.post("/api/models", json={"name": "Visible Model"})
    resp = await client.get("/models")
    assert resp.status_code == 200
    assert "Visible Model" in resp.text
