import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from maketrack import __version__
from maketrack.config import get_settings
from maketrack.logging import configure_logging


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

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    return app


app = create_app()
