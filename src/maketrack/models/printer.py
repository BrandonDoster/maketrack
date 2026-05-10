from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from maketrack.db import Base, TimestampMixin

if TYPE_CHECKING:
    from maketrack.models.model import Model
    from maketrack.models.project import Project


class Printer(Base, TimestampMixin):
    __tablename__ = "printers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    model: Mapped[str | None] = mapped_column(default=None)
    access_url: Mapped[str | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(default=None)
    photo_path: Mapped[str | None] = mapped_column(default=None)

    builds: Mapped[list["PrinterBuild"]] = relationship(
        back_populates="printer",
        cascade="all, delete-orphan",
        order_by="PrinterBuild.created_at",
    )


class PrinterBuild(Base, TimestampMixin):
    """A customization, mod, or printed addition to a printer.

    Builds optionally link to the source project (the print job that
    produced them) and to one or many models (the printed parts that
    compose the build).
    """

    __tablename__ = "printer_builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int] = mapped_column(
        ForeignKey("printers.id", ondelete="CASCADE"),
    )
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    photo_path: Mapped[str | None] = mapped_column(default=None)
    source_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        default=None,
    )

    printer: Mapped[Printer] = relationship(back_populates="builds")
    source_project: Mapped["Project | None"] = relationship(lazy="joined")
    model_links: Mapped[list["PrinterBuildModel"]] = relationship(
        back_populates="build",
        cascade="all, delete-orphan",
    )


class PrinterBuildModel(Base, TimestampMixin):
    """Join row between a printer build and a model that's part of it."""

    __tablename__ = "printer_build_models"

    printer_build_id: Mapped[int] = mapped_column(
        ForeignKey("printer_builds.id", ondelete="CASCADE"),
        primary_key=True,
    )
    model_id: Mapped[int] = mapped_column(
        ForeignKey("models.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    qty: Mapped[int] = mapped_column(default=1)
    notes: Mapped[str | None] = mapped_column(default=None)

    build: Mapped[PrinterBuild] = relationship(back_populates="model_links")
    model: Mapped["Model"] = relationship(lazy="joined")
