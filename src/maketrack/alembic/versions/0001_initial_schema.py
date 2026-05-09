"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TIMESTAMP_COLS = (
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("updated_at", sa.DateTime(), nullable=False),
)


def upgrade() -> None:
    op.create_table(
        "external_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("auth_token", sa.String(), nullable=True),
        sa.Column("field_map", sa.JSON(), nullable=True),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False, server_default="86400"),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("sync_in_progress", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *TIMESTAMP_COLS,
    )

    op.create_table(
        "filaments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("external_sources.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("external_url", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("material", sa.String(), nullable=True),
        sa.Column("color_hex", sa.String(), nullable=True),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("diameter_mm", sa.Float(), nullable=True),
        sa.Column("total_weight_g", sa.Float(), nullable=True),
        sa.Column("remaining_weight_g", sa.Float(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        *TIMESTAMP_COLS,
        sa.UniqueConstraint("source", "external_id", name="uq_filaments_source_external"),
    )
    op.create_index("ix_filaments_source", "filaments", ["source"])
    op.create_index("ix_filaments_source_id", "filaments", ["source_id"])
    op.create_index("ix_filaments_archived_at", "filaments", ["archived_at"])

    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reorder_threshold", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("vendor", sa.String(), nullable=True),
        sa.Column("vendor_sku", sa.String(), nullable=True),
        sa.Column("vendor_url", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        *TIMESTAMP_COLS,
    )

    op.create_table(
        "printers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("access_url", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        *TIMESTAMP_COLS,
    )

    # models has a forward FK to model_assets (thumbnail_asset_id). SQLite is
    # fine with the target table not yet existing because PRAGMA foreign_keys
    # is enforced at row-modify time, not at CREATE TABLE time.
    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column(
            "thumbnail_asset_id",
            sa.Integer(),
            sa.ForeignKey(
                "model_assets.id",
                ondelete="SET NULL",
                name="fk_models_thumbnail_asset_id",
                use_alter=True,
            ),
            nullable=True,
        ),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("tags", sa.String(), nullable=True),
        *TIMESTAMP_COLS,
    )

    op.create_table(
        "model_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        *TIMESTAMP_COLS,
    )
    op.create_index("ix_model_assets_model_id", "model_assets", ["model_id"])

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="planning"),
        sa.Column(
            "printer_id",
            sa.Integer(),
            sa.ForeignKey("printers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("tags", sa.String(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        *TIMESTAMP_COLS,
    )
    op.create_index("ix_projects_status", "projects", ["status"])

    op.create_table(
        "project_models",
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("models.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("qty_to_print", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=True, server_default="pending"),
        sa.Column("notes", sa.String(), nullable=True),
        *TIMESTAMP_COLS,
    )

    op.create_table(
        "project_filaments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "filament_id",
            sa.Integer(),
            sa.ForeignKey("filaments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("est_weight_g", sa.Float(), nullable=True),
        sa.Column("actual_weight_g", sa.Float(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        *TIMESTAMP_COLS,
    )
    op.create_index("ix_project_filaments_project_id", "project_filaments", ["project_id"])
    op.create_index("ix_project_filaments_filament_id", "project_filaments", ["filament_id"])

    op.create_table(
        "project_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "inventory_item_id",
            sa.Integer(),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("qty_required", sa.Integer(), nullable=False),
        sa.Column("qty_consumed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(), nullable=True),
        *TIMESTAMP_COLS,
    )
    op.create_index("ix_project_items_project_id", "project_items", ["project_id"])
    op.create_index("ix_project_items_inventory_item_id", "project_items", ["inventory_item_id"])


def downgrade() -> None:
    op.drop_index("ix_project_items_inventory_item_id", table_name="project_items")
    op.drop_index("ix_project_items_project_id", table_name="project_items")
    op.drop_table("project_items")

    op.drop_index("ix_project_filaments_filament_id", table_name="project_filaments")
    op.drop_index("ix_project_filaments_project_id", table_name="project_filaments")
    op.drop_table("project_filaments")

    op.drop_table("project_models")

    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_model_assets_model_id", table_name="model_assets")
    op.drop_table("model_assets")

    op.drop_table("models")
    op.drop_table("printers")
    op.drop_table("inventory_items")

    op.drop_index("ix_filaments_archived_at", table_name="filaments")
    op.drop_index("ix_filaments_source_id", table_name="filaments")
    op.drop_index("ix_filaments_source", table_name="filaments")
    op.drop_table("filaments")

    op.drop_table("external_sources")
