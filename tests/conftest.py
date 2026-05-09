from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from maketrack.config import reset_settings_cache
from maketrack.db import Base, get_engine, get_sessionmaker, reset_engine_cache
from maketrack.main import create_app


@pytest.fixture
def _tmp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test.db"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setenv("MAKETRACK_DB_PATH", str(db_path))
    monkeypatch.setenv("MAKETRACK_UPLOADS_PATH", str(uploads))
    reset_settings_cache()
    return db_path


@pytest.fixture
async def db_engine(_tmp_settings: Path) -> AsyncIterator[AsyncEngine]:
    await reset_engine_cache()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await reset_engine_cache()
        reset_settings_cache()


@pytest.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as s:
        yield s


@pytest.fixture
async def client(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    # Skip the lifespan: it disposes the cached engine on shutdown, which
    # would yank the rug out from under fixtures that share the same engine.
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
