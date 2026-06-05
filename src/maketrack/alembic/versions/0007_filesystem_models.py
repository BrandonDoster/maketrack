"""models: filesystem-first storage; project_models links to model_assets

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")

    # Step 1: Alter models table.
    # - Drop description (now in README body)
    # - Drop thumbnail_asset_id (now thumbnail_filename in README)
    # - Add folder_name (filesystem folder path)
    # - Add readme_hash (SHA-256 of README for change detection)
    # - Add thumbnail_filename (from README frontmatter)
    # - Add asset_ids (JSON array of model_assets.id)
    # - Add readme_malformed (flag for parse errors)
    with op.batch_alter_table("models") as batch:
        batch.drop_column("description")
        batch.drop_constraint("fk_models_thumbnail_asset_id", type_="foreignkey")
        batch.drop_column("thumbnail_asset_id")
        batch.add_column(sa.Column("folder_name", sa.String(), nullable=False))
        batch.add_column(sa.Column("readme_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("thumbnail_filename", sa.String(), nullable=True))
        batch.add_column(sa.Column("asset_ids", sa.String(), nullable=True))
        batch.add_column(sa.Column("readme_malformed", sa.Boolean(), nullable=False, server_default="0"))
        batch.create_unique_constraint("uq_models_folder_name", ["folder_name"])

    # Step 2: Drop and recreate project_models with model_asset_id instead of model_id.
    op.drop_table("project_models")

    op.create_table(
        "project_models",
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "model_asset_id",
            sa.Integer(),
            sa.ForeignKey("model_assets.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("qty_to_print", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=True, server_default="pending"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")

    # Reverse: drop project_models, restore old schema.
    op.drop_table("project_models")

    op.create_table(
        "project_models",
        sa.Column("project_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("model_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("qty_to_print", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=True, server_default="pending"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"], ondelete="RESTRICT"),
    )

    with op.batch_alter_table("models") as batch:
        batch.drop_column("readme_malformed")
        batch.drop_column("asset_ids")
        batch.drop_column("thumbnail_filename")
        batch.drop_column("readme_hash")
        batch.drop_column("folder_name")
        batch.add_column(sa.Column("thumbnail_asset_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("description", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_models_thumbnail_asset_id",
            "model_assets",
            ["thumbnail_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute("PRAGMA foreign_keys=ON")
