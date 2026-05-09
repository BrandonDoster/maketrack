import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

PACKAGE_ROOT = Path(__file__).resolve().parent
ALEMBIC_SCRIPT_DIR = PACKAGE_ROOT / "alembic"


def _build_alembic_config() -> Config:
    """Build an alembic Config without needing alembic.ini at runtime.

    env.py resolves the database URL itself from MAKETRACK_DB_PATH, so the
    only thing alembic actually needs from us is script_location.
    """
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_SCRIPT_DIR))
    return cfg


async def upgrade_to_head() -> None:
    """Apply pending migrations against the configured DB.

    env.py uses asyncio.run() internally for its async-engine setup, which
    can't run inside an existing event loop. Hop into a worker thread so
    the lifespan startup can call this safely.
    """
    cfg = _build_alembic_config()
    await asyncio.to_thread(command.upgrade, cfg, "head")
