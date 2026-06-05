from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from maketrack.db import Base, TimestampMixin, utcnow


class Model(Base, TimestampMixin):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    folder_name: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    source_type: Mapped[str | None] = mapped_column(default=None)
    source_url: Mapped[str | None] = mapped_column(default=None)
    thumbnail_filename: Mapped[str | None] = mapped_column(default=None)
    readme_hash: Mapped[str | None] = mapped_column(default=None)
    asset_ids: Mapped[str | None] = mapped_column(default=None)
    readme_malformed: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(default=None)
    tags: Mapped[str | None] = mapped_column(default=None)


class ModelAsset(Base, TimestampMixin):
    __tablename__ = "model_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"),
    )
    asset_type: Mapped[str]
    filename: Mapped[str]
    file_path: Mapped[str]
    file_size: Mapped[int | None] = mapped_column(default=None)
    sha256: Mapped[str | None] = mapped_column(default=None)
    generated: Mapped[bool] = mapped_column(default=False)
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)
