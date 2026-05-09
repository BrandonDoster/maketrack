from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from maketrack.db import utcnow
from maketrack.errors import NotFoundError
from maketrack.models.external_source import ExternalSource
from maketrack.schemas.external_source import ExternalSourceCreate, ExternalSourceUpdate


async def list_sources(
    session: AsyncSession,
    *,
    enabled_only: bool = False,
) -> Sequence[ExternalSource]:
    stmt = select(ExternalSource).order_by(ExternalSource.id)
    if enabled_only:
        stmt = stmt.where(ExternalSource.enabled.is_(True))
    return (await session.execute(stmt)).scalars().all()


async def get_source(session: AsyncSession, source_id: int) -> ExternalSource:
    src = await session.get(ExternalSource, source_id)
    if src is None:
        raise NotFoundError("external_source", source_id)
    return src


async def create_source(
    session: AsyncSession,
    payload: ExternalSourceCreate,
) -> ExternalSource:
    src = ExternalSource(**payload.model_dump())
    session.add(src)
    await session.flush()
    return src


async def update_source(
    session: AsyncSession,
    source_id: int,
    payload: ExternalSourceUpdate,
) -> ExternalSource:
    src = await get_source(session, source_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(src, key, value)
    await session.flush()
    return src


async def delete_source(session: AsyncSession, source_id: int) -> None:
    src = await get_source(session, source_id)
    await session.delete(src)
    await session.flush()


async def try_acquire_lock(session: AsyncSession, source_id: int) -> bool:
    """Atomically claim the per-source sync lock.

    Returns True if this caller now holds the lock; False if another sync is
    already in progress. Wraps the UPDATE in a fresh transaction so the lock
    visibility doesn't depend on the caller's session state.
    """
    result = await session.execute(
        update(ExternalSource)
        .where(ExternalSource.id == source_id)
        .where(ExternalSource.sync_in_progress.is_(False))
        .values(sync_in_progress=True)
    )
    await session.commit()
    return (result.rowcount or 0) > 0


async def release_lock(
    session: AsyncSession,
    source_id: int,
    *,
    last_synced_at=None,
) -> None:
    values = {"sync_in_progress": False}
    if last_synced_at is not None:
        values["last_synced_at"] = last_synced_at
    await session.execute(
        update(ExternalSource).where(ExternalSource.id == source_id).values(**values)
    )
    await session.commit()


def is_stale(source: ExternalSource, *, now=None) -> bool:
    """True iff the source has never synced or its last sync is older than ttl."""
    if not source.enabled:
        return False
    if source.last_synced_at is None:
        return True
    now = now or utcnow()
    last = source.last_synced_at
    if last.tzinfo is None:
        # SQLite gives us naive datetimes; treat them as UTC.
        from datetime import UTC

        last = last.replace(tzinfo=UTC)
    return (now - last).total_seconds() > source.ttl_seconds
