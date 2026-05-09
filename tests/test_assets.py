import io
import zipfile

from httpx import AsyncClient

from maketrack.services.assets import asset_type_from_filename
from maketrack.services.three_mf import extract_thumbnail

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\x00"
    b"\x01\xfd\xc7\xa6X\xc0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _binary_stl_bytes() -> bytes:
    """Smallest valid binary STL: 80-byte header, uint32 0 triangles."""
    return b"\x00" * 80 + (0).to_bytes(4, "little")


def _build_3mf(thumbnail_path: str | None = "Metadata/plate_1.png") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("3D/3dmodel.model", "<model/>")
        if thumbnail_path:
            zf.writestr(thumbnail_path, _PNG)
    return buf.getvalue()


def test_asset_type_from_filename() -> None:
    assert asset_type_from_filename("part.stl") == "stl"
    assert asset_type_from_filename("part.STEP") == "step"
    assert asset_type_from_filename("part.stp") == "step"
    assert asset_type_from_filename("plate.3mf") == "3mf"
    assert asset_type_from_filename("plate.gcode") == "gcode"
    assert asset_type_from_filename("photo.PNG") == "image"
    assert asset_type_from_filename("readme.md") == "other"
    assert asset_type_from_filename("noext") == "other"


def test_extract_thumbnail_from_known_path(tmp_path) -> None:
    p = tmp_path / "model.3mf"
    p.write_bytes(_build_3mf("Metadata/plate_1.png"))
    assert extract_thumbnail(p) == _PNG


def test_extract_thumbnail_falls_back_to_metadata_scan(tmp_path) -> None:
    p = tmp_path / "model.3mf"
    p.write_bytes(_build_3mf("Metadata/some_other_thumb.png"))
    assert extract_thumbnail(p) == _PNG


def test_extract_thumbnail_returns_none_when_missing(tmp_path) -> None:
    p = tmp_path / "model.3mf"
    p.write_bytes(_build_3mf(thumbnail_path=None))
    assert extract_thumbnail(p) is None


def test_extract_thumbnail_handles_bad_zip(tmp_path) -> None:
    p = tmp_path / "model.3mf"
    p.write_bytes(b"not a zip")
    assert extract_thumbnail(p) is None


async def test_upload_stl_creates_asset(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "STL Test"})
    mid = create.json()["id"]

    resp = await client.post(
        f"/api/models/{mid}/assets",
        files={
            "file": ("widget.stl", io.BytesIO(_binary_stl_bytes()), "model/stl"),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["asset_type"] == "stl"
    assert body["filename"] == "widget.stl"
    assert body["file_size"] == 84


async def test_upload_3mf_extracts_thumbnail_and_auto_sets_it(
    client: AsyncClient,
) -> None:
    create = await client.post("/api/models", json={"name": "3MF Test"})
    mid = create.json()["id"]

    resp = await client.post(
        f"/api/models/{mid}/assets",
        files={"file": ("plate.3mf", io.BytesIO(_build_3mf()), "model/3mf")},
    )
    assert resp.status_code == 201

    listing = await client.get(f"/api/models/{mid}/assets")
    rows = listing.json()
    assert len(rows) == 2  # the 3mf + the extracted thumbnail
    types = {r["asset_type"] for r in rows}
    assert types == {"3mf", "image"}
    generated = [r for r in rows if r["generated"]]
    assert len(generated) == 1
    assert generated[0]["asset_type"] == "image"

    model = (await client.get(f"/api/models/{mid}")).json()
    assert model["thumbnail_asset_id"] == generated[0]["id"]


async def test_upload_image_auto_sets_thumbnail_when_none(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "Img Test"})
    mid = create.json()["id"]

    resp = await client.post(
        f"/api/models/{mid}/assets",
        files={"file": ("hero.png", io.BytesIO(_PNG), "image/png")},
    )
    assert resp.status_code == 201
    asset_id = resp.json()["id"]

    model = (await client.get(f"/api/models/{mid}")).json()
    assert model["thumbnail_asset_id"] == asset_id


async def test_set_thumbnail_rejects_non_image(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "T"})
    mid = create.json()["id"]

    upload = await client.post(
        f"/api/models/{mid}/assets",
        files={"file": ("a.stl", io.BytesIO(_binary_stl_bytes()), "model/stl")},
    )
    asset_id = upload.json()["id"]

    resp = await client.post(
        f"/api/models/{mid}/thumbnail",
        json={"asset_id": asset_id},
    )
    assert resp.status_code == 400


async def test_download_uses_original_filename(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "DL"})
    mid = create.json()["id"]
    upload = await client.post(
        f"/api/models/{mid}/assets",
        files={"file": ("My Cool Bracket v2.stl", io.BytesIO(_binary_stl_bytes()), "model/stl")},
    )
    asset_id = upload.json()["id"]

    resp = await client.get(f"/assets/{asset_id}/download")
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    # Starlette URL-encodes filename* when it contains anything outside
    # the token character set (e.g. spaces). Either form is acceptable.
    assert "My Cool Bracket v2.stl" in cd or "My%20Cool%20Bracket%20v2.stl" in cd
    assert "attachment" in cd


async def test_delete_asset_clears_thumbnail_via_set_null(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "X"})
    mid = create.json()["id"]
    upload = await client.post(
        f"/api/models/{mid}/assets",
        files={"file": ("hero.png", io.BytesIO(_PNG), "image/png")},
    )
    asset_id = upload.json()["id"]

    model_before = (await client.get(f"/api/models/{mid}")).json()
    assert model_before["thumbnail_asset_id"] == asset_id

    delete = await client.delete(f"/api/assets/{asset_id}")
    assert delete.status_code == 204

    model_after = (await client.get(f"/api/models/{mid}")).json()
    assert model_after["thumbnail_asset_id"] is None


async def test_delete_model_cascades_assets(client: AsyncClient) -> None:
    create = await client.post("/api/models", json={"name": "C"})
    mid = create.json()["id"]
    await client.post(
        f"/api/models/{mid}/assets",
        files={"file": ("a.stl", io.BytesIO(_binary_stl_bytes()), "model/stl")},
    )

    resp = await client.delete(f"/api/models/{mid}")
    assert resp.status_code == 204

    listing = await client.get(f"/api/models/{mid}/assets")
    # Listing returns [] because the model is gone — model_id matches no rows.
    assert listing.json() == []
