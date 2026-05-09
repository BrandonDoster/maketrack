import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maketrack.services.external_sources import is_stale, list_sources
from maketrack.sync.engine import SourceFactory, sync_source


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
