from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import LocalFilamentFactory, RemoteFilamentFactory, persist


async def test_dashboard_renders(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    # Brand wordmark renders the lowercase name via the SVG <img alt>.
    assert "maketrack" in resp.text


async def test_filaments_list_renders(client: AsyncClient, session: AsyncSession) -> None:
    await persist(session, LocalFilamentFactory(name="My Black PLA", color_hex="#000000"))
    await session.commit()

    resp = await client.get("/filaments")
    assert resp.status_code == 200
    assert "My Black PLA" in resp.text


async def test_create_local_filament_via_form(client: AsyncClient) -> None:
    resp = await client.post(
        "/filaments",
        data={
            "name": "Form Created PLA",
            "material": "PLA",
            "color_hex": "#FF0000",
            "diameter_mm": "1.75",
            "total_weight_g": "1000",
            "remaining_weight_g": "1000",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/filaments"

    listing = await client.get("/filaments")
    assert "Form Created PLA" in listing.text


async def test_remote_filament_edit_shows_banner(
    client: AsyncClient, session: AsyncSession
) -> None:
    remote = await persist(
        session,
        RemoteFilamentFactory(
            name="Spoolman Spool", external_url="http://localhost:7912/spool/show/1"
        ),
    )
    await session.commit()

    resp = await client.get(f"/filaments/{remote.id}/edit")
    assert resp.status_code == 200
    assert "Read-only" in resp.text
    assert "http://localhost:7912/spool/show/1" in resp.text
    assert "Open in spoolman" in resp.text


async def test_post_remote_filament_update_returns_409_with_banner(
    client: AsyncClient, session: AsyncSession
) -> None:
    remote = await persist(session, RemoteFilamentFactory())
    await session.commit()

    resp = await client.post(
        f"/filaments/{remote.id}",
        data={"name": "tampered"},
        follow_redirects=False,
    )
    assert resp.status_code == 409
    assert "Read-only" in resp.text


async def test_sources_list_renders(client: AsyncClient, session: AsyncSession) -> None:
    from tests.factories import SpoolmanSourceFactory

    await persist(session, SpoolmanSourceFactory(name="home spoolman"))
    await session.commit()

    resp = await client.get("/settings/sources")
    assert resp.status_code == 200
    assert "home spoolman" in resp.text


async def test_old_sources_url_is_gone(client: AsyncClient) -> None:
    # /sources moved under /settings/sources in M4-followup; the old path
    # should 404 so callers don't silently miss the migration.
    resp = await client.get("/sources")
    assert resp.status_code == 404


async def test_static_vendor_files_served(client: AsyncClient) -> None:
    resp = await client.get("/static/vendor/htmx.min.js")
    assert resp.status_code == 200
    assert (
        resp.headers["content-type"].startswith("application/javascript")
        or "javascript" in resp.headers["content-type"]
    )
