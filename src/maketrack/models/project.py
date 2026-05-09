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
    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
    )
    # Float to match inventory_items.quantity — track "1.5m of XT60 wire" or
    # "0.25 kg of resin." Migration 0003 promotes the columns.
    qty_required: Mapped[float]
    qty_consumed: Mapped[float] = mapped_column(default=0.0)
    notes: Mapped[str | None] = mapped_column(default=None)
