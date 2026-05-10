"""printers.photo_path; printer_builds + printer_build_models

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Same FK toggling rationale as 0005 — see that file for details.
    op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table("printers") as batch:
        batch.add_column(sa.Column("photo_path", sa.String(), nullable=True))

    op.create_table(
        "printer_builds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "printer_id",
            sa.Integer(),
            sa.ForeignKey("printers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("photo_path", sa.String(), nullable=True),
        sa.Column(
            "source_project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_printer_builds_printer_id", "printer_builds", ["printer_id"])

    op.create_table(
        "printer_build_models",
        sa.Column(
            "printer_build_id",
            sa.Integer(),
            sa.ForeignKey("printer_builds.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("models.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")

    op.drop_table("printer_build_models")
    op.drop_index("ix_printer_builds_printer_id", table_name="printer_builds")
    op.drop_table("printer_builds")

    with op.batch_alter_table("printers") as batch:
        batch.drop_column("photo_path")

    op.execute("PRAGMA foreign_keys=ON")
