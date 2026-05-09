from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from maketrack.db import Base, TimestampMixin, utcnow


class Model(Base, TimestampMixin):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    source_type: Mapped[str | None] = mapped_column(default=None)
    source_url: Mapped[str | None] = mapped_column(default=None)
    # Set to NULL on asset delete so the row survives even if the chosen
    # thumbnail asset is removed. The asset CASCADE -> models is broken by
    # use_alter so the two tables can be created in either order.
    thumbnail_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "model_assets.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_models_thumbnail_asset_id",
        ),
        default=None,
    )
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
