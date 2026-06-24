from typing import Any

from pydantic import BaseModel, Field


class ExternalSourceBase(BaseModel):
    type: str = Field(pattern=r"^(spoolman)$")
    name: str = Field(min_length=1, max_length=200)
    base_url: str | None = None
    auth_token: str | None = None
    field_map: dict[str, Any] | None = None
    ttl_seconds: int = Field(default=86400, ge=60)
    enabled: bool = True


class ExternalSourceCreate(ExternalSourceBase):
    pass


class ExternalSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = None
    auth_token: str | None = None
    field_map: dict[str, Any] | None = None
    ttl_seconds: int | None = Field(default=None, ge=60)
    enabled: bool | None = None
