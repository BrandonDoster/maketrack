from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from maketrack.db import Base, TimestampMixin

LOCAL_SOURCE = "local"


class Filament(Base, TimestampMixin):
    __tablename__ = "filaments"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_filaments_source_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    source: Mapped[str]
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_sources.id", ondelete="RESTRICT"),
        default=None,
    )
    external_id: Mapped[str | None] = mapped_column(default=None)
    external_url: Mapped[str | None] = mapped_column(default=None)

    name: Mapped[str | None] = mapped_column(default=None)
    material: Mapped[str | None] = mapped_column(default=None)
    color_hex: Mapped[str | None] = mapped_column(default=None)
    brand: Mapped[str | None] = mapped_column(default=None)
    diameter_mm: Mapped[float | None] = mapped_column(default=None)
    total_weight_g: Mapped[float | None] = mapped_column(default=None)
    remaining_weight_g: Mapped[float | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(default=None)

    last_synced_at: Mapped[datetime | None] = mapped_column(default=None)
    archived_at: Mapped[datetime | None] = mapped_column(default=None)

    @property
    def is_local(self) -> bool:
        return self.source == LOCAL_SOURCE
