import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from maketrack import __version__
from maketrack.config import get_settings
from maketrack.db import get_engine, get_sessionmaker
from maketrack.errors import NotFoundError, RemoteFilamentError
from maketrack.logging import configure_logging
from maketrack.migrations import upgrade_to_head
from maketrack.routes.assets import router as assets_download_router
from maketrack.routes.media import router as media_router
from maketrack.routes.ui.dashboard import router as ui_dashboard_router
from maketrack.routes.ui.filaments import router as ui_filaments_router
from maketrack.routes.ui.inventory import router as ui_inventory_router
from maketrack.routes.ui.locations import router as ui_locations_router
from maketrack.routes.ui.models import router as ui_models_router
from maketrack.routes.ui.printer_builds import router as ui_printer_builds_router
from maketrack.routes.ui.printers import router as ui_printers_router
from maketrack.routes.ui.projects import router as ui_projects_router
from maketrack.routes.ui.settings import router as ui_settings_router
from maketrack.routes.ui.sources import router as ui_sources_router
from maketrack.sync import SyncScheduler, build_source
from maketrack.templating import STATIC_DIR


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    structlog.contextvars.bind_contextvars(user_id="local")
    log = structlog.get_logger()
    log.info(
        "maketrack.startup",
        version=__version__,
        bind_host=settings.bind_host,
        bind_port=settings.bind_port,
    )
    try:
        await upgrade_to_head()
        log.info("maketrack.migrations_applied")
    except Exception as exc:
        log.error("maketrack.migrations_failed", error=str(exc))
        raise
    scheduler = SyncScheduler(get_sessionmaker(), settings, source_factory=build_source)
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.stop()
        log.info("maketrack.shutdown")
        await get_engine().dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="maketrack",
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "not_found",
                "entity": exc.entity,
                "entity_id": exc.entity_id,
            },
        )

    @app.exception_handler(RemoteFilamentError)
    async def _remote_filament(_: Request, exc: RemoteFilamentError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "remote_filament_readonly",
                "source": exc.source,
                "external_url": exc.external_url,
                "message": str(exc),
            },
        )

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            structlog.get_logger().warning("healthz.db_ping_failed", error=str(exc))
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "error", "version": __version__, "detail": "db unavailable"},
            )
        return JSONResponse({"status": "ok", "version": __version__})

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker() -> FileResponse:
        # Served from the root (not /static/) so the worker's scope is "/" and
        # it can control every page. The header is belt-and-suspenders for the
        # same reason. PWA install-only — see static/sw.js.
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(assets_download_router)
    app.include_router(media_router)
    app.include_router(ui_dashboard_router)
    app.include_router(ui_filaments_router)
    app.include_router(ui_settings_router)
    app.include_router(ui_sources_router)
    app.include_router(ui_inventory_router)
    app.include_router(ui_locations_router)
    app.include_router(ui_printers_router)
    app.include_router(ui_printer_builds_router)
    app.include_router(ui_models_router)
    app.include_router(ui_projects_router)

    return app


app = create_app()
