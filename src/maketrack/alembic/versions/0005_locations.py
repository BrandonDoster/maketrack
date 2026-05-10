"""locations table; promote inventory_items.location text to FK

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-10

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="bin"),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("qr_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_locations_name"),
    )

    with op.batch_alter_table("inventory_items") as batch:
        batch.add_column(
            sa.Column(
                "location_id",
                sa.Integer(),
                sa.ForeignKey(
                    "locations.id",
                    ondelete="SET NULL",
                    name="fk_inventory_location_id",
                ),
                nullable=True,
            )
        )

    # Backfill the new structured table from existing free-text values, then
    # point each item at the matching row before dropping the old column.
    bind = op.get_bind()
    now = datetime.now(UTC)
    distinct = bind.execute(
        sa.text(
            "SELECT DISTINCT TRIM(location) AS n FROM inventory_items "
            "WHERE location IS NOT NULL AND TRIM(location) != ''"
        )
    ).all()
    for row in distinct:
        bind.execute(
            sa.text(
                "INSERT INTO locations (name, kind, created_at, updated_at) "
                "VALUES (:name, 'other', :now, :now)"
            ),
            {"name": row[0], "now": now},
        )
    bind.execute(
        sa.text(
            "UPDATE inventory_items SET location_id = ("
            "  SELECT id FROM locations WHERE locations.name = TRIM(inventory_items.location)"
            ") WHERE location IS NOT NULL AND TRIM(location) != ''"
        )
    )

    with op.batch_alter_table("inventory_items") as batch:
        batch.drop_column("location")


def downgrade() -> None:
    with op.batch_alter_table("inventory_items") as batch:
        batch.add_column(sa.Column("location", sa.String(), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE inventory_items SET location = ("
            "  SELECT name FROM locations WHERE locations.id = inventory_items.location_id"
            ") WHERE location_id IS NOT NULL"
        )
    )

    with op.batch_alter_table("inventory_items") as batch:
        batch.drop_column("location_id")

    op.drop_table("locations")
