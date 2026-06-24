"""MCP tool tests.

FastMCP `@tool()` registers a function but returns it unchanged, so we
can call each tool as a plain async function in tests rather than
spinning up the streamable-HTTP transport. The `db_engine` fixture
already gives us an isolated SQLite for each test, and the tools open
their own sessions via get_sessionmaker, so the tools see the same DB.
State is seeded through the service-backed factory helpers (which commit)
so the tools' own sessions read it back.
"""

import base64
import io
import zipfile

import pytest

from maketrack.errors import NotFoundError
from maketrack.mcp.server import (
    create_model,
    find_filament_for_project,
    get_model,
    get_project,
    list_filaments,
    list_inventory,
    list_models,
    list_printers,
    list_projects,
    project_shopping_list,
    set_model_thumbnail,
    upload_model_asset,
)
from tests.factories import (
    LocalFilamentFactory,
    PrinterFactory,
    add_model_asset,
    link_filament,
    link_item,
    make_inventory_item,
    make_model,
    make_project,
    persist,
    update_project,
)

pytestmark = pytest.mark.usefixtures("db_engine")


def _stl_bytes() -> bytes:
    return b"\x00" * 80 + (0).to_bytes(4, "little")


_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\x00"
    b"\x01\xfd\xc7\xa6X\xc0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ── read tools ────────────────────────────────────────────────────────────


async def test_list_projects_filters_by_status(session) -> None:
    a = await make_project(session, name="Active")
    await update_project(session, a.id, status="printing")
    await make_project(session, name="Idle")

    rows = await list_projects(status="printing")
    assert [r["name"] for r in rows] == ["Active"]

    rows_all = await list_projects()
    assert {r["name"] for r in rows_all} == {"Active", "Idle"}


async def test_get_project_includes_links(session) -> None:
    project = await make_project(session, name="P")
    item = await make_inventory_item(session, name="Bolt", quantity=5)
    await link_item(session, project.id, inventory_item_id=item.id, qty_required=10)

    detail = await get_project(project_id=project.id)
    assert detail["name"] == "P"
    assert len(detail["items"]) == 1
    assert detail["items"][0]["inventory_name"] == "Bolt"
    assert detail["items"][0]["inventory_on_hand"] == 5
    assert detail["models"] == []
    assert detail["filaments"] == []


async def test_get_project_missing_raises() -> None:
    with pytest.raises(NotFoundError):
        await get_project(project_id=99999)


async def test_list_models_basic(session) -> None:
    await make_model(session, name="Hero", tags=["voron"])
    await make_model(session, name="Other")
    rows = await list_models()
    names = {r["name"] for r in rows}
    assert names == {"Hero", "Other"}

    filtered = await list_models(tag="voron")
    assert [r["name"] for r in filtered] == ["Hero"]


async def test_get_model_includes_assets(session) -> None:
    mid = (await make_model(session, name="M")).id
    asset_id = await add_model_asset(session, mid, "part.stl")

    detail = await get_model(model_id=mid)
    assert detail["name"] == "M"
    assert len(detail["assets"]) == 1
    assert detail["assets"][0]["id"] == asset_id
    assert detail["assets"][0]["asset_type"] == "stl"


async def test_list_filaments(session) -> None:
    await persist(session, LocalFilamentFactory(name="Black PLA", material="PLA"))
    await persist(session, LocalFilamentFactory(name="White PETG", material="PETG"))
    await session.commit()

    pla = await list_filaments(material="PLA")
    assert [r["name"] for r in pla] == ["Black PLA"]


async def test_find_filament_for_project_coverage_states(session) -> None:
    plenty = await persist(session, LocalFilamentFactory(name="Plenty", remaining_weight_g=1000))
    short = await persist(session, LocalFilamentFactory(name="Short", remaining_weight_g=10))
    unknown = await persist(
        session, LocalFilamentFactory(name="UnknownRem", remaining_weight_g=None)
    )
    await session.commit()

    pid = (await make_project(session, name="P")).id
    await link_filament(session, pid, plenty.id, est_weight_g=200)
    await link_filament(session, pid, short.id, est_weight_g=200)
    await link_filament(session, pid, unknown.id, est_weight_g=200)

    rows = await find_filament_for_project(project_id=pid)
    coverage_by_name = {r["filament_name"]: r["coverage"] for r in rows}
    assert coverage_by_name == {
        "Plenty": "covered",
        "Short": "short",
        "UnknownRem": "unknown",
    }


async def test_project_shopping_list_global_and_per_project(session) -> None:
    item = await make_inventory_item(session, name="M3 Bolt", quantity=5)
    pid = (await make_project(session, name="P")).id
    await link_item(session, pid, inventory_item_id=item.id, qty_required=20)

    global_list = await project_shopping_list()
    assert len(global_list) == 1
    assert global_list[0]["name"] == "M3 Bolt"
    assert global_list[0]["still_to_buy"] == 15

    project_list = await project_shopping_list(project_id=pid)
    assert len(project_list) == 1
    assert project_list[0]["still_to_buy"] == 15


async def test_list_printers(session) -> None:
    await persist(session, PrinterFactory(name="Voron"))
    await session.commit()
    rows = await list_printers()
    assert [r["name"] for r in rows] == ["Voron"]


async def test_list_inventory_filters_by_category(session) -> None:
    await make_inventory_item(session, name="Bolt", category="hardware")
    await make_inventory_item(session, name="Wire", category="electronic")

    hw = await list_inventory(category="hardware")
    assert [r["name"] for r in hw] == ["Bolt"]


# ── write tools ───────────────────────────────────────────────────────────


async def test_create_model_via_mcp() -> None:
    out = await create_model(
        name="Mounted via LLM",
        description="Bracket for the Y-axis tensioner",
        source_type="local",
    )
    assert out["name"] == "Mounted via LLM"
    assert out["id"] is not None

    # Visible through the read tool too — same DB.
    rows = await list_models()
    assert any(m["name"] == "Mounted via LLM" for m in rows)


async def test_upload_model_asset_with_3mf_extracts_thumbnail(session) -> None:
    mid = (await make_model(session, name="ThreeMF")).id

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("Metadata/plate_1.png", _PNG)
    threemf = buf.getvalue()

    asset = await upload_model_asset(
        model_id=mid, filename="plate.3mf", content_base64=_b64(threemf)
    )
    assert asset["asset_type"] == "3mf"

    detail = await get_model(model_id=mid)
    types = {a["asset_type"] for a in detail["assets"]}
    assert types == {"3mf", "image"}
    assert detail["thumbnail_filename"] is not None  # auto-set from 3MF thumbnail


async def test_upload_model_asset_rejects_bad_base64() -> None:
    with pytest.raises(ValueError, match="not valid base64"):
        await upload_model_asset(model_id=1, filename="x.stl", content_base64="not===valid===")


async def test_set_model_thumbnail_via_mcp(session) -> None:
    mid = (await make_model(session, name="T")).id
    img = await upload_model_asset(model_id=mid, filename="hero.png", content_base64=_b64(_PNG))

    out = await set_model_thumbnail(model_id=mid, asset_id=img["id"])
    assert out["thumbnail_filename"] == img["filename"]
