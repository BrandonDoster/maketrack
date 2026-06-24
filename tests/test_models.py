import io

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.schemas.model import ModelCreate, ModelUpdate
from maketrack.services import assets as asset_svc
from maketrack.services import models as model_svc
from maketrack.services.models import decode_tags, read_description
from tests.factories import make_model


def _stl_bytes() -> bytes:
    return b"\x00" * 80 + (0).to_bytes(4, "little")


async def test_create_model(session: AsyncSession) -> None:
    model = await make_model(
        session,
        name="Voron Filter Mount",
        description="Mount for the Nevermore filter",
        source_type="printables",
        source_url="https://www.printables.com/model/12345",
        tags=["voron", "filter"],
    )
    assert model.name == "Voron Filter Mount"
    assert decode_tags(model.tags) == ["voron", "filter"]


async def test_tags_round_trip_via_db(session: AsyncSession) -> None:
    model = await make_model(session, name="Tagged", tags=["a", "b", "c"])

    # Re-read directly from the DB to make sure tags persisted as JSON.
    from maketrack.models.model import Model

    row = await session.get(Model, model.id)
    assert row is not None
    assert row.tags is not None
    assert decode_tags(row.tags) == ["a", "b", "c"]


async def test_list_filter_by_tag(session: AsyncSession) -> None:
    await make_model(session, name="A", tags=["foo"])
    await make_model(session, name="B", tags=["bar"])
    await make_model(session, name="C", tags=["foo", "bar"])

    rows = await model_svc.list_models(session, tag="foo")
    assert sorted(m.name for m in rows) == ["A", "C"]


async def test_invalid_source_type_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelCreate(name="X", source_type="thingyverse")


async def test_update_model(session: AsyncSession) -> None:
    model = await make_model(session, name="Original")

    updated = await model_svc.update_model(session, model.id, ModelUpdate(name="Renamed", tags=["x"]))
    await session.commit()
    assert updated.name == "Renamed"
    assert decode_tags(updated.tags) == ["x"]


async def test_models_list_renders(client: AsyncClient, session: AsyncSession) -> None:
    await make_model(session, name="Visible Model")
    resp = await client.get("/models")
    assert resp.status_code == 200
    assert "Visible Model" in resp.text


async def test_new_model_page_is_blank_draft(client: AsyncClient, session: AsyncSession) -> None:
    """'+ New model' is now a GET to a blank create form. Nothing is
    persisted until Save — no draft folder/row is created up front."""
    resp = await client.get("/models/new")
    assert resp.status_code == 200
    # Blank name field + Save button, no Delete (nothing exists yet).
    assert 'name="name"' in resp.text
    assert "Save" in resp.text
    assert "Delete model" not in resp.text
    # Visiting the form created nothing.
    assert await model_svc.list_models(session) == []


async def test_create_via_save_commits_model_and_files(
    client: AsyncClient, session: AsyncSession
) -> None:
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
    model = await model_svc.get_model(session, mid)
    assert model.name == "Voron Filter Mount"
    assert decode_tags(model.tags) == ["voron", "filter"]
    assets = await asset_svc.list_for_model(session, mid)
    assert [a.filename for a in assets] == ["part.stl"]


async def test_create_requires_name(client: AsyncClient, session: AsyncSession) -> None:
    resp = await client.post("/models", data={"name": ""}, follow_redirects=False)
    assert resp.status_code == 400
    assert "Name is required" in resp.text
    assert await model_svc.list_models(session) == []


async def test_model_detail_read_mode_hides_edit_affordances(
    client: AsyncClient, session: AsyncSession
) -> None:
    mid = (await make_model(session, name="Visible")).id

    read = await client.get(f"/models/{mid}")
    # No basic-field inputs / editor form in read mode.
    assert 'name="name"' not in read.text
    assert 'id="model-editor"' not in read.text
    # Edit toggle present.
    assert "Edit page" in read.text


async def test_model_detail_edit_mode_reveals_editor(
    client: AsyncClient, session: AsyncSession
) -> None:
    mid = (await make_model(session, name="Editable")).id

    edit = await client.get(f"/models/{mid}?edit=true")
    # Basic-field inputs render inside the single editor form posting to the model.
    assert 'value="Editable"' in edit.text
    assert "Save" in edit.text
    assert "Delete model" in edit.text
    assert f'action="/models/{mid}"' in edit.text
    # Staged-file UI (Add files) replaces the old immediate upload form.
    assert "+ Add files" in edit.text


async def test_save_updates_existing_model_and_exits(
    client: AsyncClient, session: AsyncSession
) -> None:
    mid = (await make_model(session, name="Original")).id

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

    model = await model_svc.get_model(session, mid)
    assert model.name == "Voron Filter Mount"
    assert model.source_type == "printables"
    assert decode_tags(model.tags) == ["voron", "filter"]
    assert read_description(model) == "Mount for the Nevermore filter"


async def test_sync_from_disk_button_and_route(client: AsyncClient) -> None:
    page = await client.get("/models")
    assert 'action="/models/sync"' in page.text

    resp = await client.post("/models/sync", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/models"


async def test_detail_scoped_rescan_picks_up_disk_changes(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Opening a model rescans its folder, so a file dropped into models/ on
    disk shows up without a manual full sync."""
    from maketrack.config import get_settings

    mid = (await make_model(session, name="Rescan Me")).id
    # create_model slugifies the name -> folder; drop a file into its models/.
    folder = get_settings().models_path / "rescan-me" / "models"
    (folder / "dropped.stl").write_bytes(_stl_bytes())

    detail = await client.get(f"/models/{mid}")
    assert detail.status_code == 200
    assert "dropped.stl" in detail.text

    assets = await asset_svc.list_for_model(session, mid)
    assert any(a.filename == "dropped.stl" for a in assets)


async def test_detail_renders_nested_folder_tree(
    client: AsyncClient, session: AsyncSession
) -> None:
    from maketrack.config import get_settings

    mid = (await make_model(session, name="Tree")).id
    cad = get_settings().models_path / "tree" / "models" / "cad"
    cad.mkdir(parents=True)
    (cad / "part.step").write_bytes(b"STEP")

    detail = await client.get(f"/models/{mid}")
    assert "cad/" in detail.text  # collapsible subfolder label
    assert "part.step" in detail.text


async def test_model_form_routing(client: AsyncClient, session: AsyncSession) -> None:
    # /models/new is now the blank create form (GET), not a draft-creating POST.
    assert (await client.get("/models/new")).status_code == 200

    mid = (await make_model(session, name="X")).id
    # No separate /edit route — edit is the ?edit=true toggle on the detail page.
    assert (await client.get(f"/models/{mid}/edit")).status_code == 404
