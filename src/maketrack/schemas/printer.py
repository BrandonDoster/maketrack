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
    photo_path: str | None = None
    created_at: datetime
    updated_at: datetime


class _ProjectStub(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class _ModelStub(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class PrinterBuildModelLink(BaseModel):
    """Embedded shape for a model attached to a build (qty + notes + the
    model summary so the UI doesn't need a second query)."""

    model_config = ConfigDict(from_attributes=True)

    model_id: int
    qty: int
    notes: str | None = None
    model: _ModelStub


class PrinterBuildBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    source_project_id: int | None = None


class PrinterBuildCreate(PrinterBuildBase):
    pass


class PrinterBuildUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    source_project_id: int | None = None


class PrinterBuildRead(PrinterBuildBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    printer_id: int
    photo_path: str | None = None
    source_project: _ProjectStub | None = None
    model_links: list[PrinterBuildModelLink] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PrinterBuildModelCreate(BaseModel):
    model_id: int
    qty: int = Field(default=1, ge=1)
    notes: str | None = None


class PrinterBuildModelUpdate(BaseModel):
    qty: int | None = Field(default=None, ge=1)
    notes: str | None = None
