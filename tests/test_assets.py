import io
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.services import assets as asset_svc
from maketrack.services import models as model_svc
from maketrack.services.assets import asset_type_from_filename
from maketrack.services.three_mf import extract_thumbnail
from maketrack.services.uploads import UploadError
from tests.factories import make_model, upload_model_asset

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


async def test_upload_stl_creates_asset(session: AsyncSession) -> None:
    mid = (await make_model(session, name="STL Test")).id

    asset = await upload_model_asset(session, mid, "widget.stl", data=_binary_stl_bytes())
    assert asset.asset_type == "stl"
    assert asset.filename == "widget.stl"
    assert asset.file_size == 84


async def test_upload_3mf_extracts_thumbnail_and_auto_sets_it(session: AsyncSession) -> None:
    mid = (await make_model(session, name="3MF Test")).id

    await upload_model_asset(session, mid, "plate.3mf", data=_build_3mf())

    rows = await asset_svc.list_for_model(session, mid)
    assert len(rows) == 2  # the 3mf + the extracted thumbnail
    types = {r.asset_type for r in rows}
    assert types == {"3mf", "image"}
    generated = [r for r in rows if r.generated]
    assert len(generated) == 1
    assert generated[0].asset_type == "image"

    model = await model_svc.get_model(session, mid)
    assert model.thumbnail_filename == generated[0].filename


async def test_upload_image_auto_sets_thumbnail_when_none(session: AsyncSession) -> None:
    mid = (await make_model(session, name="Img Test")).id

    asset = await upload_model_asset(session, mid, "hero.png", data=_PNG)

    model = await model_svc.get_model(session, mid)
    assert model.thumbnail_filename == asset.filename


async def test_set_thumbnail_rejects_non_image(session: AsyncSession) -> None:
    mid = (await make_model(session, name="T")).id
    asset = await upload_model_asset(session, mid, "a.stl", data=_binary_stl_bytes())

    with pytest.raises(UploadError):
        await asset_svc.set_thumbnail(session, mid, asset.id)


async def test_download_uses_original_filename(client: AsyncClient, session: AsyncSession) -> None:
    mid = (await make_model(session, name="DL")).id
    asset = await upload_model_asset(
        session, mid, "My Cool Bracket v2.stl", data=_binary_stl_bytes()
    )

    resp = await client.get(f"/assets/{asset.id}/download")
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    # Starlette URL-encodes filename* when it contains anything outside
    # the token character set (e.g. spaces). Either form is acceptable.
    assert "My Cool Bracket v2.stl" in cd or "My%20Cool%20Bracket%20v2.stl" in cd
    assert "attachment" in cd


async def test_delete_asset_clears_thumbnail(session: AsyncSession) -> None:
    mid = (await make_model(session, name="X")).id
    asset = await upload_model_asset(session, mid, "hero.png", data=_PNG)

    model_before = await model_svc.get_model(session, mid)
    assert model_before.thumbnail_filename == asset.filename

    await asset_svc.delete_asset(session, asset.id)
    await session.commit()

    model_after = await model_svc.get_model(session, mid)
    assert model_after.thumbnail_filename is None


async def test_delete_model_cascades_assets(session: AsyncSession) -> None:
    mid = (await make_model(session, name="C")).id
    await upload_model_asset(session, mid, "a.stl", data=_binary_stl_bytes())

    await model_svc.delete_model(session, mid)
    await session.commit()

    # Cascade dropped the asset rows along with the model.
    assert await asset_svc.list_for_model(session, mid) == []
