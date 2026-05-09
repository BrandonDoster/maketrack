"""project_items: float qty_required + qty_consumed

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Match the float promotion done for inventory_items in migration 0002
    # so projects can require fractional quantities (1.5 m of wire, etc.).
    with op.batch_alter_table("project_items") as batch:
        batch.alter_column(
            "qty_required",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
        )
        batch.alter_column(
            "qty_consumed",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            existing_server_default="0",
            server_default="0",
        )


def downgrade() -> None:
    with op.batch_alter_table("project_items") as batch:
        batch.alter_column(
            "qty_consumed",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            existing_server_default="0",
            server_default="0",
        )
        batch.alter_column(
            "qty_required",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
