from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import utcnow
from maketrack.errors import NotFoundError, RemoteFilamentError
from maketrack.models.filament import LOCAL_SOURCE, Filament
from maketrack.schemas.filament import FilamentCreate, FilamentUpdate


def assert_writable(filament: Filament) -> None:
    if filament.source != LOCAL_SOURCE:
        raise RemoteFilamentError(
            source=filament.source,
            external_url=filament.external_url,
        )


async def list_filaments(
    session: AsyncSession,
    *,
    material: str | None = None,
    source: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
) -> Sequence[Filament]:
    stmt = select(Filament)
    if material is not None:
        stmt = stmt.where(Filament.material == material)
    if source is not None:
        stmt = stmt.where(Filament.source == source)
    if search:
        stmt = stmt.where(Filament.name.icontains(search))
    if not include_archived:
        stmt = stmt.where(Filament.archived_at.is_(None))
    stmt = stmt.order_by(Filament.id)
    result = await session.execute(stmt)
    return result.scalars().all()


async def distinct_materials(session: AsyncSession) -> Sequence[str]:
    """Materials already represented in the table — populates the filter dropdown
    without hard-coding a list."""
    rows = (
        await session.execute(
            select(Filament.material)
            .where(Filament.material.is_not(None))
            .where(Filament.archived_at.is_(None))
            .distinct()
            .order_by(Filament.material)
        )
    ).all()
    return [m for (m,) in rows if m]


async def get_filament(session: AsyncSession, filament_id: int) -> Filament:
    filament = await session.get(Filament, filament_id)
    if filament is None:
        raise NotFoundError("filament", filament_id)
    return filament


async def create_local_filament(session: AsyncSession, payload: FilamentCreate) -> Filament:
    filament = Filament(
        source=LOCAL_SOURCE,
        **payload.model_dump(),
    )
    session.add(filament)
    await session.flush()
    return filament


async def update_filament(
    session: AsyncSession,
    filament_id: int,
    payload: FilamentUpdate,
) -> Filament:
    filament = await get_filament(session, filament_id)
    assert_writable(filament)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(filament, key, value)
    await session.flush()
    return filament


async def archive_filament(session: AsyncSession, filament_id: int) -> Filament:
    filament = await get_filament(session, filament_id)
    assert_writable(filament)
    filament.archived_at = utcnow()
    await session.flush()
    return filament
