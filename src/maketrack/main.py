import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from maketrack import __version__
from maketrack.config import get_settings
from maketrack.db import get_engine, get_sessionmaker
from maketrack.errors import NotFoundError, RemoteFilamentError
from maketrack.logging import configure_logging
from maketrack.migrations import upgrade_to_head
from maketrack.routes.assets import router as api_assets_router
from maketrack.routes.external_sources import router as api_sources_router
from maketrack.routes.filaments import router as api_filaments_router
from maketrack.routes.inventory import router as api_inventory_router
from maketrack.routes.media import router as media_router
from maketrack.routes.models import router as api_models_router
from maketrack.routes.printers import router as api_printers_router
from maketrack.routes.ui.dashboard import router as ui_dashboard_router
from maketrack.routes.ui.filaments import router as ui_filaments_router
from maketrack.routes.ui.inventory import router as ui_inventory_router
from maketrack.routes.ui.models import router as ui_models_router
from maketrack.routes.ui.printers import router as ui_printers_router
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
    scheduler = SyncScheduler(get_sessionmaker(), source_factory=build_source)
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
        title="MakeTrack",
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

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(api_filaments_router)
    app.include_router(api_sources_router)
    app.include_router(api_inventory_router)
    app.include_router(api_printers_router)
    app.include_router(api_models_router)
    app.include_router(api_assets_router)
    app.include_router(media_router)
    app.include_router(ui_dashboard_router)
    app.include_router(ui_filaments_router)
    app.include_router(ui_settings_router)
    app.include_router(ui_sources_router)
    app.include_router(ui_inventory_router)
    app.include_router(ui_printers_router)
    app.include_router(ui_models_router)

    return app


app = create_app()
