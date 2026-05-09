from sqlalchemy.orm import Mapped, mapped_column

from maketrack.db import Base, TimestampMixin


class InventoryItem(Base, TimestampMixin):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    category: Mapped[str | None] = mapped_column(default=None)
    description: Mapped[str | None] = mapped_column(default=None)
    quantity: Mapped[int] = mapped_column(default=0)
    reorder_threshold: Mapped[int | None] = mapped_column(default=None)
    unit: Mapped[str | None] = mapped_column(default=None)
    vendor: Mapped[str | None] = mapped_column(default=None)
    vendor_sku: Mapped[str | None] = mapped_column(default=None)
    vendor_url: Mapped[str | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(default=None)
