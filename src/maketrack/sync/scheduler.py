import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from maketrack.config import Settings
from maketrack.services.external_sources import list_sources
from maketrack.sync.engine import SourceFactory, sync_source
from maketrack.sync.model_scan import scan_models

DAILY_JOB_ID = "maketrack.sync.daily"
MODEL_SCAN_JOB_ID = "maketrack.sync.model_scan"


class SyncScheduler:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        source_factory: SourceFactory,
        interval_hours: int = 24,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
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
        scheduler.add_job(
            self._scan_models,
            trigger=IntervalTrigger(hours=self._interval_hours),
            id=MODEL_SCAN_JOB_ID,
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

    async def _scan_models(self) -> None:
        log = structlog.get_logger()
        try:
            async with self._sessionmaker() as session:
                result = await scan_models(session, self._settings)
                log.info(
                    "sync.model_scan_complete",
                    folders_scanned=result.folders_scanned,
                    rows_upserted=result.rows_upserted,
                    rows_deleted=result.rows_deleted,
                    errors=result.errors,
                )
        except Exception as exc:
            log.error("sync.model_scan_failed", error=str(exc))
