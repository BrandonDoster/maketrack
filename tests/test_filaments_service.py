import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError, RemoteFilamentError
from maketrack.schemas.filament import FilamentCreate, FilamentUpdate
from maketrack.services import filaments as svc
from tests.factories import LocalFilamentFactory, RemoteFilamentFactory, persist


async def test_create_local_filament_persists(session: AsyncSession) -> None:
    payload = FilamentCreate(
        name="PLA Black",
        material="PLA",
        color_hex="#000000",
        diameter_mm=1.75,
        total_weight_g=1000,
        remaining_weight_g=1000,
    )
    created = await svc.create_local_filament(session, payload)
    await session.commit()

    assert created.id is not None
    assert created.source == "local"
    assert created.is_local is True


async def test_list_filaments_excludes_archived_by_default(session: AsyncSession) -> None:
    keep = await persist(session, LocalFilamentFactory(name="keep"))
    archived = await persist(session, LocalFilamentFactory(name="gone"))
    await svc.archive_filament(session, archived.id)
    await session.commit()

    rows = await svc.list_filaments(session)
    ids = [r.id for r in rows]
    assert keep.id in ids
    assert archived.id not in ids

    rows_with_archived = await svc.list_filaments(session, include_archived=True)
    assert archived.id in [r.id for r in rows_with_archived]


async def test_list_filaments_filters_by_material(session: AsyncSession) -> None:
    await persist(session, LocalFilamentFactory(material="PLA"))
    await persist(session, LocalFilamentFactory(material="PETG"))
    await session.commit()

    pla = await svc.list_filaments(session, material="PLA")
    assert all(r.material == "PLA" for r in pla)
    assert len(pla) == 1


async def test_update_local_filament(session: AsyncSession) -> None:
    f = await persist(session, LocalFilamentFactory(name="orig"))
    await session.commit()

    updated = await svc.update_filament(session, f.id, FilamentUpdate(name="new"))
    await session.commit()

    assert updated.name == "new"


async def test_update_remote_filament_raises(session: AsyncSession) -> None:
    f = await persist(session, RemoteFilamentFactory(name="spoolman one"))
    await session.commit()

    with pytest.raises(RemoteFilamentError) as exc_info:
        await svc.update_filament(session, f.id, FilamentUpdate(name="hijack"))
    assert exc_info.value.source == "spoolman"
    assert exc_info.value.external_url is not None


async def test_archive_remote_filament_raises(session: AsyncSession) -> None:
    f = await persist(session, RemoteFilamentFactory())
    await session.commit()

    with pytest.raises(RemoteFilamentError):
        await svc.archive_filament(session, f.id)


async def test_get_missing_raises_not_found(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await svc.get_filament(session, 999999)
