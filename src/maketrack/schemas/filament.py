from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FilamentBase(BaseModel):
    name: str | None = None
    material: str | None = None
    color_hex: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    brand: str | None = None
    diameter_mm: float | None = Field(default=None, gt=0)
    total_weight_g: float | None = Field(default=None, ge=0)
    remaining_weight_g: float | None = Field(default=None, ge=0)
    notes: str | None = None


class FilamentCreate(FilamentBase):
    pass


class FilamentUpdate(BaseModel):
    name: str | None = None
    material: str | None = None
    color_hex: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    brand: str | None = None
    diameter_mm: float | None = Field(default=None, gt=0)
    total_weight_g: float | None = Field(default=None, ge=0)
    remaining_weight_g: float | None = Field(default=None, ge=0)
    notes: str | None = None


class FilamentRead(FilamentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: int | None
    external_id: str | None
    external_url: str | None
    last_synced_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
