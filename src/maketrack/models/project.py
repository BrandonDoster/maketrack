from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from maketrack.db import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="planning")
    printer_id: Mapped[int | None] = mapped_column(
        ForeignKey("printers.id", ondelete="SET NULL"),
        default=None,
    )
    notes: Mapped[str | None] = mapped_column(default=None)
    tags: Mapped[str | None] = mapped_column(default=None)
    # Two slots: cover (render / before / borrowed) + after (completion shot).
    cover_photo_path: Mapped[str | None] = mapped_column(default=None)
    completed_photo_path: Mapped[str | None] = mapped_column(default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)


class ProjectModel(Base, TimestampMixin):
    __tablename__ = "project_models"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    model_id: Mapped[int] = mapped_column(
        ForeignKey("models.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    qty_to_print: Mapped[int] = mapped_column(default=1)
    status: Mapped[str | None] = mapped_column(default="pending")
    notes: Mapped[str | None] = mapped_column(default=None)


class ProjectFilament(Base, TimestampMixin):
    __tablename__ = "project_filaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    filament_id: Mapped[int] = mapped_column(
        ForeignKey("filaments.id", ondelete="RESTRICT"),
    )
    est_weight_g: Mapped[float | None] = mapped_column(default=None)
    actual_weight_g: Mapped[float | None] = mapped_column(default=None)
    role: Mapped[str | None] = mapped_column(default=None)


class ProjectItem(Base, TimestampMixin):
    __tablename__ = "project_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    # Nullable so a BOM row can exist before the user has created the matching
    # inventory_items row (e.g. "I know I need M3x8 SHCS, I haven't typed it
    # in yet"). When linked, RESTRICT on inventory deletion still applies.
    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        default=None,
    )
    # Used while unlinked (free-text). When the link is set, these stay as
    # the user-typed values for reference, but display falls through to the
    # joined InventoryItem.
    name: Mapped[str | None] = mapped_column(default=None)
    unit: Mapped[str | None] = mapped_column(default=None)
    qty_required: Mapped[float]
    qty_consumed: Mapped[float] = mapped_column(default=0.0)
    notes: Mapped[str | None] = mapped_column(default=None)

    @property
    def display_name(self) -> str | None:
        """Best name available without loading the linked InventoryItem.

        list_project_items() resolves the joined inventory item and overrides
        this on the response; this attribute exists so that a freshly-created
        ProjectItem (e.g. the row we just inserted in add_item) has a
        sensible display value when there's no joined entity yet.
        """
        return self.name
