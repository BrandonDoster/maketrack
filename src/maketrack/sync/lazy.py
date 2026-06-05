from datetime import datetime

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maketrack.config import Settings
from maketrack.models.model import Model
from maketrack.services.external_sources import is_stale, list_sources
from maketrack.sync.engine import SourceFactory, sync_source
from maketrack.sync.model_scan import scan_models


async def ensure_fresh_sources(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    source_factory: SourceFactory,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Sync any enabled source whose last sync exceeds its TTL.

    Called from any route that reads filaments. Blocks on the sync to make
    sure the response reflects fresh data. If no one browses, no sync runs.
    """
    async with sessionmaker() as session:
        sources = await list_sources(session, enabled_only=True)

    log = structlog.get_logger()
    for source in sources:
        if not is_stale(source):
            continue
        try:
            await sync_source(
                sessionmaker,
                source.id,
                source_factory=source_factory,
                http_client=http_client,
            )
        except Exception as exc:
            log.warning("sync.lazy_failed", source_id=source.id, error=str(exc))


async def ensure_fresh_models(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Scan models_path if any model is older than TTL.

    Called from routes that list/detail models. Blocks on the scan to ensure
    fresh data. If no one browses, no scan runs.
    """
    async with sessionmaker() as session:
        # Check the oldest model's updated_at.
        result = await session.execute(select(func.min(Model.updated_at)).select_from(Model))
        oldest_updated = result.scalar()

    now = datetime.now(datetime.UTC)
    ttl_seconds = settings.default_ttl_seconds

    if oldest_updated is None or (now - oldest_updated).total_seconds() > ttl_seconds:
        log = structlog.get_logger()
        try:
            async with sessionmaker() as session:
                await scan_models(session, settings)
        except Exception as exc:
            log.warning("sync.lazy_model_scan_failed", error=str(exc))
