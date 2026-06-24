import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.schemas.external_source import ExternalSourceCreate
from maketrack.services import external_sources as source_svc
from tests.factories import SpoolmanSourceFactory, persist


async def test_create_source(session: AsyncSession) -> None:
    src = await source_svc.create_source(
        session,
        ExternalSourceCreate(
            type="spoolman",
            name="home",
            base_url="http://localhost:7912",
            ttl_seconds=3600,
            enabled=True,
        ),
    )
    await session.commit()
    assert src.type == "spoolman"
    assert src.enabled is True


async def test_list_sources(session: AsyncSession) -> None:
    await persist(session, SpoolmanSourceFactory(name="a"))
    await persist(session, SpoolmanSourceFactory(name="b"))
    await session.commit()

    assert len(await source_svc.list_sources(session)) == 2


async def test_disable_source_archives_filaments(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Disabling a source through the settings form archives its filaments
    (the disable→archive orchestration lives in the UI route)."""
    src = await persist(session, SpoolmanSourceFactory())
    from maketrack.models.filament import Filament

    f = Filament(source="spoolman", external_id="1", name="X")
    session.add(f)
    await session.commit()

    # Posting the edit form without the `enabled` checkbox disables it.
    resp = await client.post(
        f"/settings/sources/{src.id}",
        data={"name": src.name},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    await session.refresh(f)
    assert f.archived_at is not None


async def test_invalid_source_type_rejected() -> None:
    with pytest.raises(ValidationError):
        ExternalSourceCreate(type="octoprint", name="x")
