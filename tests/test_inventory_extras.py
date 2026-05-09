import io
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.config import get_settings
from tests.factories import InventoryItemFactory, persist


async def test_quantity_accepts_decimal_via_api(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/inventory",
        json={"name": "XT60 wire", "unit": "m", "quantity": 1.5},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["quantity"] == 1.5


async def test_quantity_rejects_negative(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/inventory",
        json={"name": "x", "quantity": -0.5},
    )
    assert resp.status_code == 422


async def test_location_field_round_trips(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/inventory",
        json={"name": "M3 Heatsets", "location": "Bin A3", "quantity": 50},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["location"] == "Bin A3"


_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\x00"
    b"\x01\xfd\xc7\xa6X\xc0\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def test_photo_upload_via_form_then_served(client: AsyncClient) -> None:
    resp = await client.post(
        "/inventory",
        data={"name": "Item with Photo", "quantity": "1"},
        files={"photo": ("tiny.png", io.BytesIO(_PNG_1X1), "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    listing = await client.get("/inventory")
    # Item shows up
    assert "Item with Photo" in listing.text
    # The list template embeds <img src="/media/inventory/<uuid>"> for items
    # with a photo. Pull the src out and fetch it.
    import re

    match = re.search(r"/media/inventory/[0-9a-f]+\.png", listing.text)
    assert match, f"no /media/inventory link in {listing.text[:500]!r}"
    media = await client.get(match.group(0))
    assert media.status_code == 200
    assert media.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_photo_upload_rejects_non_image(client: AsyncClient) -> None:
    resp = await client.post(
        "/inventory",
        data={"name": "Bad", "quantity": "1"},
        files={"photo": ("evil.exe", io.BytesIO(b"MZ\x90"), "application/x-msdownload")},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "unsupported photo type" in resp.text


async def test_photo_removed_when_item_deleted(client: AsyncClient, session: AsyncSession) -> None:
    item = await persist(session, InventoryItemFactory(photo_path="inventory/abc123"))
    await session.commit()

    # Drop a stub file at that path.
    uploads = get_settings().uploads_path
    target = uploads / "inventory" / "abc123"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"stub")
    assert target.exists()

    resp = await client.post(f"/inventory/{item.id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert not target.exists()


async def test_media_route_blocks_path_traversal(client: AsyncClient) -> None:
    resp = await client.get("/media/../../etc/passwd")
    # Either 404 because the resolved path escapes the uploads root, or 404
    # because the file doesn't exist; both are fine. Refuse 200 either way.
    assert resp.status_code != 200


async def test_media_route_returns_404_for_missing(client: AsyncClient) -> None:
    resp = await client.get("/media/inventory/does-not-exist")
    assert resp.status_code == 404


async def test_uploads_path_is_test_isolated(client: AsyncClient) -> None:
    """Sanity: tests must not be writing to /uploads on the host."""
    settings = get_settings()
    # tmp_path lives under /private/tmp or /tmp; reject the prod default.
    assert "uploads" in str(settings.uploads_path)
    assert Path("/uploads") not in settings.uploads_path.parents
    assert settings.uploads_path != Path("/uploads")
