import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maketrack.services.external_sources import list_sources
from maketrack.sync.engine import SourceFactory, sync_source

DAILY_JOB_ID = "maketrack.sync.daily"


class SyncScheduler:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        source_factory: SourceFactory,
        interval_hours: int = 24,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._source_factory = source_factory
        self._interval_hours = interval_hours
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        if self._scheduler is not None:
            return
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(hours=self._interval_hours),
            id=DAILY_JOB_ID,
            replace_existing=True,
        )
        scheduler.start()
        self._scheduler = scheduler

    def stop(self) -> None:
        if self._scheduler is None:
            return
        self._scheduler.shutdown(wait=False)
        self._scheduler = None

    async def _tick(self) -> None:
        log = structlog.get_logger()
        async with self._sessionmaker() as session:
            sources = await list_sources(session, enabled_only=True)
        for source in sources:
            try:
                await sync_source(
                    self._sessionmaker,
                    source.id,
                    source_factory=self._source_factory,
                )
            except Exception as exc:
                log.warning("sync.scheduled_failed", source_id=source.id, error=str(exc))
