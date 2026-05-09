from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PrinterBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    access_url: str | None = None
    notes: str | None = None


class PrinterCreate(PrinterBase):
    pass


class PrinterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    access_url: str | None = None
    notes: str | None = None


class PrinterRead(PrinterBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
