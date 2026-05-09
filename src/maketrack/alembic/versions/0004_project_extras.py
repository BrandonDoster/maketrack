"""project_items: nullable inventory FK + name/unit; projects: photo paths

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # project_items: relax inventory_item_id to nullable, add free-text
    # name/unit for unlinked BOM rows. SQLite needs batch mode to drop the
    # NOT NULL constraint.
    with op.batch_alter_table("project_items") as batch:
        batch.alter_column(
            "inventory_item_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch.add_column(sa.Column("name", sa.String(), nullable=True))
        batch.add_column(sa.Column("unit", sa.String(), nullable=True))

    # projects: two photo slots (cover + after). Stored as relative paths
    # under uploads/ same as inventory photos and model assets.
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("cover_photo_path", sa.String(), nullable=True))
        batch.add_column(sa.Column("completed_photo_path", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("completed_photo_path")
        batch.drop_column("cover_photo_path")

    with op.batch_alter_table("project_items") as batch:
        batch.drop_column("unit")
        batch.drop_column("name")
        batch.alter_column(
            "inventory_item_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
