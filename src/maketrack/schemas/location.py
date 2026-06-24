from pydantic import BaseModel, Field

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
