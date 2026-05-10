from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

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
    "locations",
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


def test_locations_migration_backfills_existing_text_locations(
    alembic_config: Config,
) -> None:
    """Bring the schema up to 0004 (still has the text `location` field),
    seed a couple of items, then run 0005 and confirm each item ends up
    pointed at a row in the new locations table with the same name."""
    db_path = alembic_config.attributes["maketrack_db_path"]

    command.upgrade(alembic_config, "0004")

    sync_engine = create_engine(f"sqlite:///{db_path}")
    try:
        with sync_engine.begin() as conn:
            # PRAGMA foreign_keys=ON to mirror prod — our event listener
            # turns it on for every connection, and the migration must cope
            # with the project_items → inventory_items FK during the batch
            # rebuild dance.
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(
                text(
                    "INSERT INTO inventory_items "
                    "(name, quantity, location, created_at, updated_at) VALUES "
                    "('M3 SHCS', 100, 'Bin A3', '2026-05-10', '2026-05-10'),"
                    "('M3 Heatset', 50, 'Bin A3', '2026-05-10', '2026-05-10'),"
                    "('PTFE Tube', 5, 'Drawer 4', '2026-05-10', '2026-05-10'),"
                    "('Spare', 1, NULL, '2026-05-10', '2026-05-10')"
                )
            )
            # Seed a project + a project_items row referencing one of the
            # inventory items, so the batch rebuild has to actually navigate
            # the FK from project_items.
            conn.execute(
                text(
                    "INSERT INTO projects (name, status, created_at, updated_at) "
                    "VALUES ('p', 'planning', '2026-05-10', '2026-05-10')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO project_items "
                    "(project_id, inventory_item_id, qty_required, qty_consumed, "
                    "created_at, updated_at) VALUES "
                    "(1, 1, 5, 0, '2026-05-10', '2026-05-10')"
                )
            )
    finally:
        sync_engine.dispose()

    command.upgrade(alembic_config, "0005")

    sync_engine = create_engine(f"sqlite:///{db_path}")
    try:
        with sync_engine.connect() as conn:
            # Two distinct strings → two location rows.
            location_names = {
                row[0] for row in conn.execute(text("SELECT name FROM locations")).all()
            }
            assert location_names == {"Bin A3", "Drawer 4"}

            # Items previously sharing a string now share an FK; the null
            # row stays null.
            rows = conn.execute(
                text(
                    "SELECT i.name, l.name FROM inventory_items i "
                    "LEFT JOIN locations l ON l.id = i.location_id "
                    "ORDER BY i.id"
                )
            ).all()
            assert rows == [
                ("M3 SHCS", "Bin A3"),
                ("M3 Heatset", "Bin A3"),
                ("PTFE Tube", "Drawer 4"),
                ("Spare", None),
            ]

            # Old text column is gone.
            cols = {c["name"] for c in inspect(sync_engine).get_columns("inventory_items")}
            assert "location" not in cols
            assert "location_id" in cols

            # The FK from project_items survived the batch rebuild — the
            # row we seeded above still resolves through the join.
            project_items = conn.execute(
                text(
                    "SELECT i.name FROM project_items pi "
                    "JOIN inventory_items i ON i.id = pi.inventory_item_id"
                )
            ).all()
            assert project_items == [("M3 SHCS",)]
    finally:
        sync_engine.dispose()
