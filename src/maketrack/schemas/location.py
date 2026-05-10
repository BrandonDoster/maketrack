from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

LOCATION_KINDS = ("bin", "shelf", "drawer", "other")
_KIND_PATTERN = r"^(bin|shelf|drawer|other)$"


class LocationBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="bin", pattern=_KIND_PATTERN)


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, pattern=_KIND_PATTERN)


class LocationRead(LocationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None = None
    qr_code: str | None = None
    created_at: datetime
    updated_at: datetime
