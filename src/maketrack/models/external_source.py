from datetime import datetime
from typing import Any

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from maketrack.db import Base, TimestampMixin


class ExternalSource(Base, TimestampMixin):
    __tablename__ = "external_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str]
    name: Mapped[str]
    base_url: Mapped[str | None] = mapped_column(default=None)
    auth_token: Mapped[str | None] = mapped_column(default=None)
    field_map: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    ttl_seconds: Mapped[int] = mapped_column(default=86400)
    last_synced_at: Mapped[datetime | None] = mapped_column(default=None)
    sync_in_progress: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)
