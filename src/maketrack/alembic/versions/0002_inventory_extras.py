"""inventory: decimal quantity, location, photo_path

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite can't ALTER COLUMN type in place; batch_alter_table rebuilds
    # the table. Existing INTEGER values convert cleanly to REAL because
    # SQLite stores numerics dynamically.
    with op.batch_alter_table("inventory_items") as batch:
        batch.alter_column(
            "quantity",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            existing_server_default="0",
            server_default="0",
        )
        batch.alter_column(
            "reorder_threshold",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=True,
        )
        batch.add_column(sa.Column("location", sa.String(), nullable=True))
        batch.add_column(sa.Column("photo_path", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inventory_items") as batch:
        batch.drop_column("photo_path")
        batch.drop_column("location")
        batch.alter_column(
            "reorder_threshold",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
        batch.alter_column(
            "quantity",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            existing_server_default="0",
            server_default="0",
        )
