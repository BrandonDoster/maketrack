from httpx import AsyncClient


async def test_healthz_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


async def test_healthz_sets_request_id(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


async def test_healthz_echoes_request_id(client: AsyncClient) -> None:
    response = await client.get("/healthz", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"
