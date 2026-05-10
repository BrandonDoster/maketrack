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


async def test_new_model_button_creates_draft_in_edit_mode(client: AsyncClient) -> None:
    """Mirror of the printer flow — '+ New model' POSTs to /models/new,
    creates a stub named 'New model', and drops the user on the detail
    page in edit mode."""
    resp = await client.post("/models/new", follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/models/")
    assert location.endswith("?edit=true")

    detail = await client.get(location)
    assert detail.status_code == 200
    assert 'value="New model"' in detail.text
    assert "Done editing" in detail.text
    assert "Delete model" in detail.text


async def test_model_detail_read_mode_hides_edit_affordances(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "Visible"})
    mid = create.json()["id"]

    read = await client.get(f"/models/{mid}")
    # No basic-field inputs, no upload form in read mode.
    assert 'name="name"' not in read.text
    assert f'action="/models/{mid}/assets"' not in read.text
    # Edit toggle present.
    assert "Edit page" in read.text


async def test_model_detail_edit_mode_reveals_forms(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "Editable"})
    mid = create.json()["id"]

    edit = await client.get(f"/models/{mid}?edit=true")
    # Basic-field inputs render.
    assert 'value="Editable"' in edit.text
    assert "Done editing" in edit.text
    assert "Delete model" in edit.text
    # Asset upload form is back in edit mode.
    assert f'action="/models/{mid}/assets"' in edit.text


async def test_done_editing_saves_and_exits(client: AsyncClient) -> None:
    create = await client.post("/models/new", follow_redirects=False)
    mid = int(create.headers["location"].split("/")[2].split("?")[0])

    save = await client.post(
        f"/models/{mid}",
        data={
            "name": "Voron Filter Mount",
            "source_type": "printables",
            "source_url": "",
            "tags": "voron, filter",
            "description": "Mount for the Nevermore filter",
            "notes": "",
        },
        follow_redirects=False,
    )
    assert save.status_code == 303
    # Exits edit mode.
    assert save.headers["location"] == f"/models/{mid}"

    api = await client.get(f"/api/models/{mid}")
    body = api.json()
    assert body["name"] == "Voron Filter Mount"
    assert body["source_type"] == "printables"
    assert body["tags"] == ["voron", "filter"]


async def test_old_model_form_routes_are_gone(client: AsyncClient) -> None:
    assert (await client.get("/models/new")).status_code in (404, 422)

    create = await client.post("/models/new", follow_redirects=False)
    mid = int(create.headers["location"].split("/")[2].split("?")[0])
    assert (await client.get(f"/models/{mid}/edit")).status_code == 404
