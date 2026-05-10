from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from maketrack.db import Base, TimestampMixin

if TYPE_CHECKING:
    from maketrack.models.inventory import InventoryItem

LOCATION_KINDS = ("bin", "shelf", "drawer", "other")


class Location(Base, TimestampMixin):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[str] = mapped_column(default="bin")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), default=None
    )
    qr_code: Mapped[str | None] = mapped_column(default=None)

    parent: Mapped["Location | None"] = relationship(
        "Location",
        remote_side="Location.id",
        back_populates="children",
    )
    children: Mapped[list["Location"]] = relationship("Location", back_populates="parent")
    items: Mapped[list["InventoryItem"]] = relationship(back_populates="location")
