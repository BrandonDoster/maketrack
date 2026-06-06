import io

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.services.models import decode_tags


def _stl_bytes() -> bytes:
    return b"\x00" * 80 + (0).to_bytes(4, "little")


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


async def test_new_model_page_is_blank_draft(client: AsyncClient) -> None:
    """'+ New model' is now a GET to a blank create form. Nothing is
    persisted until Save — no draft folder/row is created up front."""
    resp = await client.get("/models/new")
    assert resp.status_code == 200
    # Blank name field + Save button, no Delete (nothing exists yet).
    assert 'name="name"' in resp.text
    assert "Save" in resp.text
    assert "Delete model" not in resp.text
    # Visiting the form created nothing.
    assert (await client.get("/api/models")).json() == []


async def test_create_via_save_commits_model_and_files(client: AsyncClient) -> None:
    """Saving the create form writes the model + uploads staged files in one
    multipart POST to /models."""
    resp = await client.post(
        "/models",
        data={"name": "Voron Filter Mount", "source_type": "printables", "tags": "voron, filter"},
        files={"files": ("part.stl", io.BytesIO(_stl_bytes()), "model/stl")},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    location = resp.headers["location"]
    assert location.startswith("/models/")
    assert not location.endswith("?edit=true")  # lands in read mode

    mid = int(location.rstrip("/").split("/")[-1])
    body = (await client.get(f"/api/models/{mid}")).json()
    assert body["name"] == "Voron Filter Mount"
    assert body["tags"] == ["voron", "filter"]
    assets = (await client.get(f"/api/models/{mid}/assets")).json()
    assert [a["filename"] for a in assets] == ["part.stl"]


async def test_create_requires_name(client: AsyncClient) -> None:
    resp = await client.post("/models", data={"name": ""}, follow_redirects=False)
    assert resp.status_code == 400
    assert "Name is required" in resp.text
    assert (await client.get("/api/models")).json() == []


async def test_model_detail_read_mode_hides_edit_affordances(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "Visible"})
    mid = create.json()["id"]

    read = await client.get(f"/models/{mid}")
    # No basic-field inputs / editor form in read mode.
    assert 'name="name"' not in read.text
    assert 'id="model-editor"' not in read.text
    # Edit toggle present.
    assert "Edit page" in read.text


async def test_model_detail_edit_mode_reveals_editor(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "Editable"})
    mid = create.json()["id"]

    edit = await client.get(f"/models/{mid}?edit=true")
    # Basic-field inputs render inside the single editor form posting to the model.
    assert 'value="Editable"' in edit.text
    assert "Save" in edit.text
    assert "Delete model" in edit.text
    assert f'action="/models/{mid}"' in edit.text
    # Staged-file UI (Add files) replaces the old immediate upload form.
    assert "+ Add files" in edit.text


async def test_save_updates_existing_model_and_exits(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "Original"})
    mid = create.json()["id"]

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
    assert body["description"] == "Mount for the Nevermore filter"


async def test_sync_from_disk_button_and_route(client: AsyncClient) -> None:
    page = await client.get("/models")
    assert 'action="/models/sync"' in page.text

    resp = await client.post("/models/sync", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/models"


async def test_detail_scoped_rescan_picks_up_disk_changes(client: AsyncClient) -> None:
    """Opening a model rescans its folder, so a file dropped into models/ on
    disk shows up without a manual full sync."""
    from maketrack.config import get_settings

    mid = (await client.post("/api/models", json={"name": "Rescan Me"})).json()["id"]
    # create_model slugifies the name -> folder; drop a file into its models/.
    folder = get_settings().models_path / "rescan-me" / "models"
    (folder / "dropped.stl").write_bytes(_stl_bytes())

    detail = await client.get(f"/models/{mid}")
    assert detail.status_code == 200
    assert "dropped.stl" in detail.text

    assets = (await client.get(f"/api/models/{mid}/assets")).json()
    assert any(a["filename"] == "dropped.stl" for a in assets)


async def test_detail_renders_nested_folder_tree(client: AsyncClient) -> None:
    from maketrack.config import get_settings

    mid = (await client.post("/api/models", json={"name": "Tree"})).json()["id"]
    cad = get_settings().models_path / "tree" / "models" / "cad"
    cad.mkdir(parents=True)
    (cad / "part.step").write_bytes(b"STEP")

    detail = await client.get(f"/models/{mid}")
    assert "cad/" in detail.text  # collapsible subfolder label
    assert "part.step" in detail.text


async def test_model_form_routing(client: AsyncClient) -> None:
    # /models/new is now the blank create form (GET), not a draft-creating POST.
    assert (await client.get("/models/new")).status_code == 200

    create = await client.post("/api/models", json={"name": "X"})
    mid = create.json()["id"]
    # No separate /edit route — edit is the ?edit=true toggle on the detail page.
    assert (await client.get(f"/models/{mid}/edit")).status_code == 404
