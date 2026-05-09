from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from maketrack.config import reset_settings_cache


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    db_path = tmp_path / "alembic.db"
    monkeypatch.setenv("MAKETRACK_DB_PATH", str(db_path))
    reset_settings_cache()
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.attributes["maketrack_db_path"] = db_path
    try:
        yield cfg
    finally:
        reset_settings_cache()


EXPECTED_TABLES = {
    "external_sources",
    "filaments",
    "inventory_items",
    "printers",
    "models",
    "model_assets",
    "projects",
    "project_models",
    "project_filaments",
    "project_items",
    "alembic_version",
}


def test_alembic_round_trip_creates_then_drops_all_tables(alembic_config: Config) -> None:
    db_path = alembic_config.attributes["maketrack_db_path"]

    command.upgrade(alembic_config, "head")

    sync_engine = create_engine(f"sqlite:///{db_path}")
    try:
        tables = set(inspect(sync_engine).get_table_names())
        assert EXPECTED_TABLES.issubset(tables), f"missing tables: {EXPECTED_TABLES - tables}"
    finally:
        sync_engine.dispose()

    command.downgrade(alembic_config, "base")

    sync_engine = create_engine(f"sqlite:///{db_path}")
    try:
        remaining = set(inspect(sync_engine).get_table_names())
        # Only alembic_version survives a full downgrade.
        assert remaining <= {"alembic_version"}
    finally:
        sync_engine.dispose()
