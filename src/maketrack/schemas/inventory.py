from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

INVENTORY_CATEGORIES = ("hardware", "electronic", "tool", "other")


class InventoryItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, pattern=r"^(hardware|electronic|tool|other)$")
    description: str | None = None
    quantity: int = Field(default=0, ge=0)
    reorder_threshold: int | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    vendor: str | None = None
    vendor_sku: str | None = None
    vendor_url: str | None = None
    notes: str | None = None


class InventoryItemCreate(InventoryItemBase):
    pass


class InventoryItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, pattern=r"^(hardware|electronic|tool|other)$")
    description: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    reorder_threshold: int | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    vendor: str | None = None
    vendor_sku: str | None = None
    vendor_url: str | None = None
    notes: str | None = None


class InventoryItemRead(InventoryItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
