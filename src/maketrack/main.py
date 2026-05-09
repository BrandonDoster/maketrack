import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from maketrack import __version__
from maketrack.config import get_settings
from maketrack.db import get_engine
from maketrack.errors import NotFoundError, RemoteFilamentError
from maketrack.logging import configure_logging
from maketrack.routes.filaments import router as filaments_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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
    yield
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

    app.include_router(filaments_router)

    return app


app = create_app()
