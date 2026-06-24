import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.errors import NotFoundError, RemoteFilamentError
from maketrack.schemas.filament import FilamentCreate, FilamentUpdate
from maketrack.services import filaments as filament_svc
from tests.factories import LocalFilamentFactory, RemoteFilamentFactory, persist


async def test_create_then_get_filament(session: AsyncSession) -> None:
    created = await filament_svc.create_local_filament(
        session,
        FilamentCreate(
            name="Black PLA",
            material="PLA",
            color_hex="#000000",
            diameter_mm=1.75,
            total_weight_g=1000,
            remaining_weight_g=1000,
        ),
    )
    await session.commit()
    assert created.source == "local"
    assert created.material == "PLA"

    fetched = await filament_svc.get_filament(session, created.id)
    assert fetched.id == created.id


async def test_list_filaments(session: AsyncSession) -> None:
    await persist(session, LocalFilamentFactory(material="PLA"))
    await persist(session, LocalFilamentFactory(material="PETG"))
    await session.commit()

    assert len(await filament_svc.list_filaments(session)) == 2
    assert len(await filament_svc.list_filaments(session, material="PLA")) == 1


async def test_patch_remote_filament_raises_readonly(session: AsyncSession) -> None:
    remote = await persist(session, RemoteFilamentFactory())
    await session.commit()

    with pytest.raises(RemoteFilamentError) as exc:
        await filament_svc.update_filament(session, remote.id, FilamentUpdate(name="tampered"))
    assert exc.value.source == "spoolman"
    assert exc.value.external_url == remote.external_url


async def test_patch_missing_raises_not_found(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await filament_svc.update_filament(session, 999999, FilamentUpdate(name="x"))


async def test_invalid_color_hex_rejected() -> None:
    with pytest.raises(ValidationError):
        FilamentCreate(color_hex="not-a-color")
