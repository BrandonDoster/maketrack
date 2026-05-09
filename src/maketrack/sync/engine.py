from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maketrack.db import utcnow
from maketrack.models.external_source import ExternalSource
from maketrack.models.filament import Filament
from maketrack.services.external_sources import release_lock, try_acquire_lock
from maketrack.sources.base import ExternalFilament, FilamentSource


class SyncOutcome(StrEnum):
    OK = "ok"
    SKIPPED_DISABLED = "skipped_disabled"
    SKIPPED_LOCKED = "skipped_locked"
    SKIPPED_NOT_FOUND = "skipped_not_found"
    FAILED = "failed"


@dataclass
class SyncResult:
    source_id: int
    started_at: datetime
    finished_at: datetime
    outcome: SyncOutcome
    rows_upserted: int = 0
    rows_archived: int = 0
    error: str | None = None


SourceFactory = Callable[[ExternalSource, httpx.AsyncClient | None], FilamentSource]


async def sync_source(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: int,
    *,
    source_factory: SourceFactory,
    http_client: httpx.AsyncClient | None = None,
) -> SyncResult:
    """Sync one external source per CLAUDE.md sync semantics.

    Acquires the per-source lock atomically; if another sync holds it,
    returns SKIPPED_LOCKED without touching anything else. On adapter
    failure, leaves existing rows untouched (no archive sweep) and releases
    the lock without bumping last_synced_at.
    """
    started = utcnow()
    log = structlog.get_logger().bind(source_id=source_id, started_at=started.isoformat())

    async with sessionmaker() as session:
        source = await session.get(ExternalSource, source_id)
        if source is None:
            log.warning("sync.source_missing")
            return SyncResult(
                source_id=source_id,
                started_at=started,
                finished_at=utcnow(),
                outcome=SyncOutcome.SKIPPED_NOT_FOUND,
            )
        if not source.enabled:
            log.info("sync.skipped", reason="disabled")
            return SyncResult(
                source_id=source_id,
                started_at=started,
                finished_at=utcnow(),
                outcome=SyncOutcome.SKIPPED_DISABLED,
            )

        acquired = await try_acquire_lock(session, source_id)
        if not acquired:
            log.info("sync.skipped", reason="locked")
            return SyncResult(
                source_id=source_id,
                started_at=started,
                finished_at=utcnow(),
                outcome=SyncOutcome.SKIPPED_LOCKED,
            )

        # Snapshot the fields we need outside the session.
        source_type = source.type
        adapter = source_factory(source, http_client)

    try:
        external_filaments = await adapter.list_spools()
    except Exception as exc:
        log.warning("sync.failed", error=str(exc), phase="fetch")
        async with sessionmaker() as session:
            await release_lock(session, source_id)
        finished = utcnow()
        return SyncResult(
            source_id=source_id,
            started_at=started,
            finished_at=finished,
            outcome=SyncOutcome.FAILED,
            error=str(exc),
        )

    try:
        async with sessionmaker() as session:
            upserted, archived = await _apply_sync(
                session, source_id, source_type, external_filaments
            )
            await session.commit()
    except Exception as exc:
        log.warning("sync.failed", error=str(exc), phase="apply")
        async with sessionmaker() as session:
            await release_lock(session, source_id)
        finished = utcnow()
        return SyncResult(
            source_id=source_id,
            started_at=started,
            finished_at=finished,
            outcome=SyncOutcome.FAILED,
            error=str(exc),
        )

    finished = utcnow()
    async with sessionmaker() as session:
        await release_lock(session, source_id, last_synced_at=finished)

    log.info(
        "sync.completed",
        finished_at=finished.isoformat(),
        rows_upserted=upserted,
        rows_archived=archived,
    )
    return SyncResult(
        source_id=source_id,
        started_at=started,
        finished_at=finished,
        outcome=SyncOutcome.OK,
        rows_upserted=upserted,
        rows_archived=archived,
    )


async def _apply_sync(
    session: AsyncSession,
    source_id: int,
    source_type: str,
    external_filaments: list[ExternalFilament],
) -> tuple[int, int]:
    returned_ids = {ef.external_id for ef in external_filaments}
    now = utcnow()

    # Load every row we already have for this source so we can decide
    # upsert vs. archive sweep without N round-trips.
    existing_rows = (
        (await session.execute(select(Filament).where(Filament.source == source_type)))
        .scalars()
        .all()
    )
    by_external_id = {row.external_id: row for row in existing_rows}

    upserted = 0
    for ef in external_filaments:
        row = by_external_id.get(ef.external_id)
        if row is None:
            row = Filament(
                source=source_type,
                source_id=source_id,
                external_id=ef.external_id,
            )
            session.add(row)
        # Always update source_id in case a row was previously created under
        # a different ExternalSource of the same type.
        row.source_id = source_id
        row.external_url = ef.external_url
        row.name = ef.name
        row.material = ef.material
        row.color_hex = ef.color_hex
        row.brand = ef.brand
        row.diameter_mm = ef.diameter_mm
        row.total_weight_g = ef.total_weight_g
        row.remaining_weight_g = ef.remaining_weight_g
        row.last_synced_at = now
        # Reappearance: a spool we'd archived is back, so un-archive it.
        if row.archived_at is not None:
            row.archived_at = None
        upserted += 1

    # Archive sweep: rows we used to have but the source no longer returns.
    if returned_ids:
        sweep_stmt = (
            update(Filament)
            .where(Filament.source == source_type)
            .where(Filament.archived_at.is_(None))
            .where(Filament.external_id.notin_(returned_ids))
            .values(archived_at=now)
        )
    else:
        # Nothing came back — archive every still-active row from this source.
        sweep_stmt = (
            update(Filament)
            .where(Filament.source == source_type)
            .where(Filament.archived_at.is_(None))
            .values(archived_at=now)
        )
    sweep_result = await session.execute(sweep_stmt)
    archived = sweep_result.rowcount or 0

    return upserted, archived


async def archive_all_for_source(session: AsyncSession, source_type: str) -> int:
    """Mark every row from this source as archived. Used when a source is disabled."""
    now = utcnow()
    result = await session.execute(
        update(Filament)
        .where(Filament.source == source_type)
        .where(Filament.archived_at.is_(None))
        .values(archived_at=now)
    )
    return result.rowcount or 0
