from sqlalchemy.orm import Mapped, mapped_column

from maketrack.db import Base, TimestampMixin


class InventoryItem(Base, TimestampMixin):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    category: Mapped[str | None] = mapped_column(default=None)
    description: Mapped[str | None] = mapped_column(default=None)
    # Quantity is float so users can track "1.5m of XT60 wire" or "0.25 kg
    # of resin." UI rounds to 2 decimal places for display.
    quantity: Mapped[float] = mapped_column(default=0.0)
    reorder_threshold: Mapped[float | None] = mapped_column(default=None)
    unit: Mapped[str | None] = mapped_column(default=None)
    location: Mapped[str | None] = mapped_column(default=None)
    photo_path: Mapped[str | None] = mapped_column(default=None)
    vendor: Mapped[str | None] = mapped_column(default=None)
    vendor_sku: Mapped[str | None] = mapped_column(default=None)
    vendor_url: Mapped[str | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(default=None)
