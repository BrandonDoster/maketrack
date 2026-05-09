from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import SpoolmanSourceFactory, persist


async def test_settings_index_renders(client: AsyncClient, session: AsyncSession) -> None:
    await persist(session, SpoolmanSourceFactory(name="home"))
    await session.commit()

    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "External sources" in resp.text
    assert "Appearance" in resp.text


async def test_theme_post_sets_cookie_and_redirects(client: AsyncClient) -> None:
    resp = await client.post("/settings/theme", data={"theme": "dark"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings"
    assert "maketrack_theme=dark" in resp.headers.get("set-cookie", "")


async def test_invalid_theme_falls_back_to_default(client: AsyncClient) -> None:
    resp = await client.post("/settings/theme", data={"theme": "neon"}, follow_redirects=False)
    assert resp.status_code == 303
    # An invalid theme stores 'auto', not the bogus value.
    assert "maketrack_theme=auto" in resp.headers.get("set-cookie", "")


async def test_settings_dropdown_reflects_current_theme(client: AsyncClient) -> None:
    # Set the cookie first.
    await client.post("/settings/theme", data={"theme": "light"}, follow_redirects=False)
    resp = await client.get("/settings")
    assert resp.status_code == 200
    # The currently selected option in the dropdown is 'Light'.
    assert 'value="light" selected' in resp.text


async def test_sources_under_settings_path(client: AsyncClient, session: AsyncSession) -> None:
    src = await persist(session, SpoolmanSourceFactory(name="under-settings"))
    await session.commit()

    new_form = await client.get("/settings/sources/new")
    assert new_form.status_code == 200

    edit_form = await client.get(f"/settings/sources/{src.id}/edit")
    assert edit_form.status_code == 200
    assert "under-settings" in edit_form.text
